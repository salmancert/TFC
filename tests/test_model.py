"""Forecasting tests, including recovery of known ground truth."""
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

import synthetic
from travel_cost_forecasting import data_processing as dp
from travel_cost_forecasting.fares import FareCache, FareQuote
from travel_cost_forecasting.model import (AllowanceModel, TripCostForecaster,
                                           evaluate)

RATES = {'CN': 80.0, 'SE': 90.0, 'PL': 85.0, 'US': 100.0, 'GB': 110.0,
         'IN': 50.0, 'SG': 120.0, 'BR': 70.0, 'DE': 95.0, 'ES': 95.0}


@pytest.fixture(scope='module')
def fitted():
    trips = dp.preprocess_data(synthetic.make_export(n_trips=900),
                               allowance_rates=RATES)
    return TripCostForecaster(RATES).fit(trips), trips


def test_allowance_is_exact_arithmetic_not_a_prediction():
    model = AllowanceModel({'CN': 80.0}, basis='dest')
    result = model.predict('SE', 'CN', month=4, year=2026, days=7)
    assert result['amount'] == 80.0 * 7
    assert result['source'] == 'policy'


def test_allowance_scales_exactly_linearly_with_days():
    model = AllowanceModel({'CN': 80.0}, basis='dest')
    one = model.predict('SE', 'CN', 4, 2026, days=1)['amount']
    ten = model.predict('SE', 'CN', 4, 2026, days=10)['amount']
    assert ten == pytest.approx(one * 10)


def test_recovers_known_annual_trend(fitted):
    forecaster, _ = fitted
    assert forecaster.air.annual_trend == pytest.approx(synthetic.ANNUAL_TREND, abs=0.02)


def test_recovers_known_seasonality(fitted):
    """Peak months must come out dearer than trough months."""
    forecaster, _ = fitted
    assert forecaster.air.month_factors[4] > forecaster.air.month_factors[8]
    assert forecaster.air.month_factors[10] > forecaster.air.month_factors[7]
    for month in range(1, 13):
        assert forecaster.air.month_factors[month] == pytest.approx(
            synthetic.MONTH_FACTORS[month], abs=0.12)


@pytest.mark.parametrize('home,dest', [('SE', 'CN'), ('DE', 'GB'), ('US', 'BR'),
                                       ('SE', 'PL'), ('IN', 'SG')])
def test_route_fares_are_within_ten_percent_of_truth(fitted, home, dest):
    forecaster, _ = fitted
    predicted = forecaster.predict(home, dest, 6, 4, 2025)['components']['air']['amount']
    expected = synthetic.expected_fare(home, dest, 4, 2025)
    assert predicted == pytest.approx(expected, rel=0.10)


def test_hotel_scales_with_nights_not_trip_count(fitted):
    forecaster, _ = fitted
    three = forecaster.predict('SE', 'CN', 3, 4, 2025)['components']['hotel']
    nine = forecaster.predict('SE', 'CN', 9, 4, 2025)['components']['hotel']
    assert three['nights'] == 2 and nine['nights'] == 8
    assert nine['amount'] == pytest.approx(three['amount'] * 4, rel=1e-6)


def test_components_sum_to_the_total(fitted):
    forecaster, _ = fitted
    result = forecaster.predict('SE', 'CN', 7, 4, 2026)
    assert sum(c['amount'] for c in result['components'].values()) == pytest.approx(
        result['total'])
    assert sum(result['breakdown'].values()) == pytest.approx(result['total'])


def test_breakdown_is_not_a_fixed_ratio_split(fitted):
    """The old model split one number by constant ratios; this must not.

    A short trip is dominated by the air fare, a long one by per-night and
    per-day costs, so the air share has to fall as duration grows.
    """
    forecaster, _ = fitted
    short = forecaster.predict('SE', 'CN', 2, 4, 2026)
    long = forecaster.predict('SE', 'CN', 20, 4, 2026)
    short_air_share = short['breakdown']['Air Ticket'] / short['total']
    long_air_share = long['breakdown']['Air Ticket'] / long['total']
    assert short_air_share > long_air_share + 0.2


def test_unseen_route_falls_back_through_the_hierarchy(fitted):
    forecaster, _ = fitted
    # PL is a known destination, but never from IN in the synthetic data.
    result = forecaster.predict('IN', 'PL', 5, 5, 2026)
    assert result['components']['air']['basis'] in ('destination', 'global')
    assert result['total'] > 0


def test_thin_route_is_shrunk_toward_its_destination():
    """One freak observation must not become the route's estimate."""
    base = synthetic.make_export(n_trips=400)
    freak = base[base['Report Country'] == 'CN'].head(4).copy()
    freak['Report Home Country Name'] = 'PL'
    freak['Report Key'] = ['9999999901', '9999999902', '9999999903', '9999999904']
    freak.loc[freak['Report Entry Expense Type Name'] == 'AIR TICKET',
              'Amount in EUR'] = 9000.0
    trips = dp.preprocess_data(pd.concat([base, freak], ignore_index=True),
                               allowance_rates=RATES)
    forecaster = TripCostForecaster(RATES).fit(trips)
    predicted = forecaster.predict('PL', 'CN', 5, 4, 2025)['components']['air']['amount']
    assert predicted < 9000.0 * 0.8   # pulled well below the outlier


def _seed_cache(tmp_path, price, age_days=0.0, n=2, origin='ARN', dest='PVG'):
    cache = FareCache(str(tmp_path / 'fares.sqlite3'))
    collected = datetime.now(timezone.utc) - timedelta(days=age_days)
    for i in range(n):
        cache.put(FareQuote(origin=origin, destination=dest,
                            departure_date=date.today() + timedelta(days=21 + i),
                            price_eur=price, provider='test', lead_days=21 + i,
                            collected_at=collected))
    return cache


def test_live_fare_moves_the_estimate_toward_the_market(fitted, tmp_path):
    forecaster, _ = fitted
    historical = forecaster.predict('SE', 'CN', 7, 4, 2026)['components']['air']['amount']
    cache = _seed_cache(tmp_path, price=historical * 1.8)
    anchored = forecaster.predict('SE', 'CN', 7, 4, 2026,
                                  fare_cache=cache)['components']['air']
    assert anchored['amount'] > historical
    assert anchored['amount'] < historical * 1.8   # blended, not replaced
    assert anchored['source'] == 'live-anchored'


def test_stale_quotes_are_ignored(fitted, tmp_path):
    forecaster, _ = fitted
    historical = forecaster.predict('SE', 'CN', 7, 4, 2026)['components']['air']['amount']
    cache = _seed_cache(tmp_path, price=historical * 2, age_days=400)
    result = forecaster.predict('SE', 'CN', 7, 4, 2026,
                                fare_cache=cache)['components']['air']
    assert result['amount'] == pytest.approx(historical)
    assert result['source'] == 'historical'


def test_older_quotes_carry_less_weight_than_fresh_ones(fitted, tmp_path):
    forecaster, _ = fitted
    historical = forecaster.predict('SE', 'CN', 7, 4, 2026)['components']['air']['amount']
    fresh = forecaster.predict('SE', 'CN', 7, 4, 2026, fare_cache=_seed_cache(
        tmp_path / 'a', price=historical * 1.8))['components']['air']
    old = forecaster.predict('SE', 'CN', 7, 4, 2026, fare_cache=_seed_cache(
        tmp_path / 'b', price=historical * 1.8, age_days=20))['components']['air']
    assert fresh['anchor_weight'] > old['anchor_weight']
    assert fresh['amount'] > old['amount']


def test_live_fare_leads_when_there_is_no_route_history(tmp_path):
    """The case the sample export is actually in: no air data at all."""
    trips = dp.preprocess_data(synthetic.make_export(n_trips=200),
                               allowance_rates=RATES)
    trips['air_eur'] = 0.0                       # wipe all air history
    forecaster = TripCostForecaster(RATES).fit(trips)
    assert forecaster.predict('SE', 'CN', 7, 4, 2026)['components']['air']['amount'] == 0.0

    cache = _seed_cache(tmp_path, price=900.0)
    anchored = forecaster.predict('SE', 'CN', 7, 4, 2026,
                                  fare_cache=cache)['components']['air']
    assert anchored['amount'] > 700.0            # live quote dominates
    assert anchored['source'] == 'live-anchored'


def test_absurd_live_quote_cannot_dominate_solid_history(fitted, tmp_path):
    forecaster, _ = fitted
    historical = forecaster.predict('SE', 'CN', 7, 4, 2026)['components']['air']['amount']
    cache = _seed_cache(tmp_path, price=historical * 50, n=6)
    anchored = forecaster.predict('SE', 'CN', 7, 4, 2026,
                                  fare_cache=cache)['components']['air']['amount']
    # The anchor ratio is clipped, so a bad quote can at most double the figure.
    assert anchored <= historical * 2.0


def test_domestic_trips_are_not_anchored_to_a_flight(fitted, tmp_path):
    forecaster, _ = fitted
    cache = _seed_cache(tmp_path, price=5000.0, origin='PVG', dest='PVG')
    result = forecaster.predict('CN', 'CN', 3, 4, 2026,
                                fare_cache=cache)['components']['air']
    assert result['source'] == 'historical'


def test_backtest_split_is_chronological(fitted):
    _, trips = fitted
    metrics = evaluate(trips, RATES, test_fraction=0.2)
    assert metrics['n_train'] + metrics['n_test'] == len(trips)
    assert metrics['total']['mdape'] < 25.0


def test_evaluate_reports_cleanly_on_tiny_data():
    trips = dp.preprocess_data(synthetic.make_export(n_trips=3), allowance_rates=RATES)
    assert 'error' in evaluate(trips, RATES)


def test_model_survives_a_save_load_round_trip(fitted, tmp_path):
    forecaster, _ = fitted
    path = forecaster.save(str(tmp_path / 'model.pkl'))
    reloaded = TripCostForecaster.load(path)
    assert reloaded.predict('SE', 'CN', 7, 4, 2026)['total'] == pytest.approx(
        forecaster.predict('SE', 'CN', 7, 4, 2026)['total'])
