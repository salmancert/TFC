"""Fare cache, refresh scheduling and the Amadeus client contract."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

import synthetic
from travel_cost_forecasting import config
from travel_cost_forecasting import data_processing as dp
from travel_cost_forecasting.countries import resolve_airport
from travel_cost_forecasting.fares import FareCache, FareQuote, StaticFareProvider
from travel_cost_forecasting.fares import refresh as fare_refresh
from travel_cost_forecasting.fares.amadeus import AmadeusFareProvider
from travel_cost_forecasting.fares.base import FareProviderError, OfflineError

RATES = {'CN': 80.0, 'SE': 90.0, 'PL': 85.0, 'US': 100.0, 'GB': 110.0,
         'IN': 50.0, 'SG': 120.0, 'BR': 70.0, 'DE': 95.0, 'ES': 95.0}


@pytest.fixture
def cache(tmp_path):
    return FareCache(str(tmp_path / 'fares.sqlite3'))


@pytest.fixture
def trips():
    return dp.preprocess_data(synthetic.make_export(n_trips=300), allowance_rates=RATES)


def _quote(price, origin='ARN', dest='PVG', age_days=0.0, lead=21):
    return FareQuote(origin=origin, destination=dest,
                     departure_date=date.today() + timedelta(days=lead),
                     price_eur=price, provider='test', lead_days=lead,
                     collected_at=datetime.now(timezone.utc) - timedelta(days=age_days))


# -- cache -----------------------------------------------------------------
def test_market_price_is_the_median_of_recent_quotes(cache):
    for price in (500.0, 600.0, 2000.0):
        cache.put(_quote(price))
    price, n, age = cache.market_price('ARN', 'PVG')
    assert price == 600.0            # median, so the outlier does not win
    assert n == 3 and age < 1.0


def test_uncovered_route_returns_nothing(cache):
    assert cache.market_price('ARN', 'JFK') == (None, 0, None)


def test_quotes_older_than_the_window_are_excluded(cache):
    cache.put(_quote(500.0, age_days=90))
    assert cache.market_price('ARN', 'PVG', max_age_days=30)[0] is None
    assert cache.market_price('ARN', 'PVG', max_age_days=120)[0] == 500.0


def test_cache_is_append_only_so_history_is_preserved(cache):
    cache.put(_quote(500.0))
    cache.put(_quote(700.0))
    assert len(cache.recent_quotes('ARN', 'PVG')) == 2


def test_stats_report_coverage(cache):
    cache.put(_quote(500.0))
    cache.put(_quote(400.0, origin='FRA', dest='LHR'))
    stats = cache.stats()
    assert stats['quotes'] == 2 and stats['routes'] == 2
    assert stats['last_refresh'] is not None


# -- route ranking ---------------------------------------------------------
def test_routes_are_ranked_by_how_often_they_are_flown(trips):
    ranked = fare_refresh.rank_routes(trips)
    assert not ranked.empty
    assert ranked['trips'].is_monotonic_decreasing
    assert (ranked['origin'] != ranked['destination']).all()


def test_domestic_routes_are_excluded_from_fare_lookups(trips):
    ranked = fare_refresh.rank_routes(trips)
    assert not (ranked['home_country'] == ranked['dest_country']).any()


def test_ranking_resolves_country_codes_to_hub_airports(trips):
    ranked = fare_refresh.rank_routes(trips)
    row = ranked[(ranked['home_country'] == 'SE') & (ranked['dest_country'] == 'CN')]
    assert row.iloc[0]['origin'] == resolve_airport('SE')
    assert row.iloc[0]['destination'] == resolve_airport('CN')


def test_empty_history_produces_no_routes():
    import pandas as pd
    assert fare_refresh.rank_routes(pd.DataFrame()).empty


# -- selection and budget --------------------------------------------------
def test_daily_run_takes_the_busiest_routes(trips, cache):
    ranked = fare_refresh.rank_routes(trips)
    selected = fare_refresh.select_routes(ranked, cache, 'daily', top_n=3)
    assert len(selected) == 3
    assert selected['trips'].tolist() == ranked['trips'].head(3).tolist()


def test_weekly_run_rotates_the_tail_least_recently_tried_first(trips, cache):
    ranked = fare_refresh.rank_routes(trips)
    tail = fare_refresh.select_routes(ranked, cache, 'weekly', top_n=2, batch=2)
    first = (tail.iloc[0]['origin'], tail.iloc[0]['destination'])
    cache.log_attempt(first[0], first[1], 'ok', True)

    again = fare_refresh.select_routes(ranked, cache, 'weekly', top_n=2, batch=2)
    # The route just attempted should no longer be at the front of the queue.
    assert (again.iloc[0]['origin'], again.iloc[0]['destination']) != first


def test_refresh_stops_at_the_call_budget(trips, cache):
    ranked = fare_refresh.rank_routes(trips)
    provider = StaticFareProvider(default_price=500.0)
    summary = fare_refresh.refresh_fares(provider, cache, ranked,
                                         lead_days=[21, 45], budget=5)
    assert summary['calls'] == 5
    assert summary['budget_exhausted'] is True
    assert provider.calls == 5


def test_refresh_stores_one_quote_per_route_and_lead_day(trips, cache):
    ranked = fare_refresh.rank_routes(trips).head(2)
    summary = fare_refresh.refresh_fares(StaticFareProvider(default_price=500.0),
                                         cache, ranked, lead_days=[21, 45], budget=99)
    assert summary['stored'] == 4
    assert summary['errors'] == 0


def test_uncovered_routes_are_counted_not_fatal(trips, cache):
    ranked = fare_refresh.rank_routes(trips).head(2)
    summary = fare_refresh.refresh_fares(StaticFareProvider(default_price=None),
                                         cache, ranked, lead_days=[21], budget=99)
    assert summary['uncovered'] == 2 and summary['stored'] == 0


def test_one_failing_route_does_not_abort_the_run(trips, cache):
    class Flaky(StaticFareProvider):
        def search(self, origin, destination, departure_date, return_date=None,
                   cabin='ECONOMY'):
            if origin == 'FRA':
                raise FareProviderError('boom')
            return super().search(origin, destination, departure_date, return_date, cabin)

    ranked = fare_refresh.rank_routes(trips)
    summary = fare_refresh.refresh_fares(Flaky(default_price=500.0), cache,
                                         ranked, lead_days=[21], budget=99)
    assert summary['errors'] > 0
    assert summary['stored'] > 0        # the healthy routes still got through


# -- offline guarantees ----------------------------------------------------
def test_offline_mode_blocks_the_refresh_entirely(trips, cache, monkeypatch):
    monkeypatch.setattr(config, 'OFFLINE_MODE', True)
    provider = StaticFareProvider(default_price=500.0)
    summary = fare_refresh.refresh_fares(provider, cache,
                                         fare_refresh.rank_routes(trips), budget=99)
    assert summary['offline'] is True
    assert summary['calls'] == 0
    assert provider.calls == 0


def test_offline_mode_builds_no_provider(monkeypatch):
    monkeypatch.setattr(config, 'OFFLINE_MODE', True)
    monkeypatch.setattr(config, 'AMADEUS_CLIENT_ID', 'id')
    monkeypatch.setattr(config, 'AMADEUS_CLIENT_SECRET', 'secret')
    assert fare_refresh.build_provider() is None


def test_no_credentials_builds_no_provider(monkeypatch):
    monkeypatch.setattr(config, 'OFFLINE_MODE', False)
    monkeypatch.setattr(config, 'AMADEUS_CLIENT_ID', None)
    assert fare_refresh.build_provider() is None


def test_amadeus_refuses_to_call_out_in_offline_mode(monkeypatch):
    monkeypatch.setattr(config, 'OFFLINE_MODE', True)
    provider = AmadeusFareProvider(client_id='id', client_secret='secret')
    with pytest.raises(OfflineError):
        provider.search('ARN', 'PVG', '2026-04-01')


# -- Amadeus client --------------------------------------------------------
class _Response:
    def __init__(self, status_code, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


class _FakeSession:
    """Stands in for requests.Session so the client is tested without network."""

    def __init__(self, get_responses):
        self._get_responses = list(get_responses)
        self.get_calls = []
        self.post_calls = 0

    def post(self, url, data=None, headers=None, timeout=None):
        self.post_calls += 1
        return _Response(200, {'access_token': 'tok', 'expires_in': 1799})

    def get(self, url, params=None, headers=None, timeout=None):
        self.get_calls.append(params)
        return self._get_responses.pop(0)

    def close(self):
        pass


def _offers(*prices):
    return {'data': [{'price': {'grandTotal': str(p)}} for p in prices]}


def _provider(session, monkeypatch):
    monkeypatch.setattr(config, 'OFFLINE_MODE', False)
    return AmadeusFareProvider(client_id='id', client_secret='secret',
                               session=session)


def test_amadeus_requests_eur_and_the_right_route(monkeypatch):
    session = _FakeSession([_Response(200, _offers(500, 600, 700))])
    quote = _provider(session, monkeypatch).search(
        'ARN', 'PVG', date(2026, 4, 1), date(2026, 4, 8))
    params = session.get_calls[0]
    assert params['originLocationCode'] == 'ARN'
    assert params['destinationLocationCode'] == 'PVG'
    assert params['departureDate'] == '2026-04-01'
    assert params['returnDate'] == '2026-04-08'
    assert params['currencyCode'] == 'EUR'
    assert quote.trip_type == 'ROUND_TRIP'


def test_amadeus_uses_a_low_percentile_not_the_absolute_cheapest(monkeypatch):
    """The cheapest offer is usually an unbookable red-eye with two layovers."""
    session = _FakeSession([_Response(200, _offers(100, 500, 520, 540, 900))])
    quote = _provider(session, monkeypatch).search('ARN', 'PVG', date(2026, 4, 1))
    assert quote.price_eur > 100.0
    assert quote.price_eur <= 540.0


def test_amadeus_returns_none_when_no_offers_exist(monkeypatch):
    session = _FakeSession([_Response(200, {'data': []})])
    assert _provider(session, monkeypatch).search('ARN', 'PVG', date(2026, 4, 1)) is None


def test_amadeus_treats_an_unsupported_route_as_uncovered(monkeypatch):
    """A 400 means this route is not sellable, not that the run should fail."""
    session = _FakeSession([_Response(400, {}, 'bad route')])
    assert _provider(session, monkeypatch).search('ARN', 'XXX', date(2026, 4, 1)) is None


def test_amadeus_retries_on_throttling_then_succeeds(monkeypatch):
    monkeypatch.setattr('time.sleep', lambda *_: None)
    session = _FakeSession([_Response(429, {}, 'slow down'),
                            _Response(200, _offers(400, 450))])
    quote = _provider(session, monkeypatch).search('ARN', 'PVG', date(2026, 4, 1))
    assert quote is not None
    assert len(session.get_calls) == 2


def test_amadeus_reauthenticates_after_a_rejected_token(monkeypatch):
    session = _FakeSession([_Response(401, {}, 'expired'),
                            _Response(200, _offers(400))])
    provider = _provider(session, monkeypatch)
    assert provider.search('ARN', 'PVG', date(2026, 4, 1)) is not None
    assert session.post_calls == 2       # token fetched again


def test_amadeus_gives_up_cleanly_after_repeated_failures(monkeypatch):
    monkeypatch.setattr('time.sleep', lambda *_: None)
    session = _FakeSession([_Response(500, {}, 'boom')] * 3)
    with pytest.raises(FareProviderError):
        _provider(session, monkeypatch).search('ARN', 'PVG', date(2026, 4, 1))


def test_amadeus_reports_missing_credentials_clearly(monkeypatch):
    monkeypatch.setattr(config, 'OFFLINE_MODE', False)
    provider = AmadeusFareProvider(client_id=None, client_secret=None)
    with pytest.raises(FareProviderError, match='AMADEUS_CLIENT_ID'):
        provider.search('ARN', 'PVG', date(2026, 4, 1))
