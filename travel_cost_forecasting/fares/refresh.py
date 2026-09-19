"""Scheduled fare refresh.

There are 77 supported countries, so 5,852 ordered country pairs. Amadeus'
free tier allows roughly 2,000 calls a month, which means refreshing every
route is impossible and refreshing at random is wasteful. Instead the routes
that actually appear in the historical export are ranked by how often they are
flown: the busiest get refreshed daily, the long tail rotates weekly by
staleness, and every run stops at a hard call budget.

Run from cron, Task Scheduler, or a SharePoint-synced machine:

    python cli.py refresh-fares --cadence daily     # e.g. 06:00 every day
    python cli.py refresh-fares --cadence weekly    # e.g. 03:00 on Sundays
"""
import logging
from datetime import date, timedelta

import pandas as pd

from .. import config
from ..countries import resolve_airport
from .base import FareProviderError, OfflineError

logger = logging.getLogger(__name__)

#: Fallback return leg when a route has no usable duration history.
DEFAULT_TRIP_NIGHTS = 5


def rank_routes(trips):
    """Ranks flyable routes by historical frequency.

    Returns:
        A DataFrame with origin/destination IATA codes, trip counts and the
        median trip length, ordered busiest first.
    """
    if trips.empty:
        return pd.DataFrame(columns=['home_country', 'dest_country', 'origin',
                                     'destination', 'trips', 'median_nights'])

    flights = trips[trips['home_country'] != trips['dest_country']].copy()
    if flights.empty:
        return pd.DataFrame(columns=['home_country', 'dest_country', 'origin',
                                     'destination', 'trips', 'median_nights'])

    grouped = (flights.groupby(['home_country', 'dest_country'])
               .agg(trips=('report_key', 'nunique'),
                    median_nights=('nights', 'median'))
               .reset_index())

    grouped['origin'] = [resolve_airport(c) for c in grouped['home_country']]
    grouped['destination'] = [resolve_airport(c) for c in grouped['dest_country']]
    # Drop anything we cannot turn into an airport pair, and same-hub routes
    # (two countries mapping to one hub cannot be flown between).
    grouped = grouped.dropna(subset=['origin', 'destination'])
    grouped = grouped[grouped['origin'] != grouped['destination']]

    grouped['median_nights'] = (grouped['median_nights']
                                .fillna(DEFAULT_TRIP_NIGHTS)
                                .clip(lower=1, upper=30).astype(int))
    return grouped.sort_values('trips', ascending=False).reset_index(drop=True)


def select_routes(ranked, cache, cadence='daily', top_n=None, batch=None, now=None):
    """Chooses which routes to refresh on this run.

    'daily' takes the busiest routes. 'weekly' rotates through the remaining
    tail, least-recently-attempted first, so every route is eventually covered
    without ever exceeding the budget.
    """
    if ranked.empty:
        return ranked

    top_n = config.FARE_DAILY_TOP_N if top_n is None else top_n
    batch = config.FARE_WEEKLY_BATCH if batch is None else batch

    if cadence == 'daily':
        return ranked.head(top_n).copy()

    tail = ranked.iloc[top_n:].copy()
    if tail.empty:
        # Fewer routes than the daily cut -- rotate the whole set instead of
        # doing nothing, so a small deployment still refreshes weekly.
        tail = ranked.copy()

    epoch = pd.Timestamp('1970-01-01', tz='UTC')
    attempts = []
    for _, row in tail.iterrows():
        last = cache.last_attempt(row['origin'], row['destination'])
        attempts.append(pd.Timestamp(last) if last is not None else epoch)
    tail['last_attempt'] = attempts
    tail = tail.sort_values(['last_attempt', 'trips'], ascending=[True, False])
    return tail.head(batch).drop(columns=['last_attempt'])


def refresh_fares(provider, cache, routes, lead_days=None, budget=None,
                  today=None):
    """Fetches and stores quotes for the selected routes.

    One API call is made per route per lead day. The run stops cleanly once the
    budget is spent, and a failure on one route never aborts the rest.

    Returns:
        A dict summarising the run.
    """
    lead_days = lead_days or config.FARE_LEAD_DAYS
    budget = config.FARE_CALL_BUDGET if budget is None else budget
    today = today or date.today()

    summary = {'calls': 0, 'stored': 0, 'routes': 0, 'uncovered': 0,
               'errors': 0, 'budget_exhausted': False}

    if config.OFFLINE_MODE:
        logger.warning('Offline mode enabled -- skipping fare refresh entirely')
        summary['offline'] = True
        return summary

    for _, route in routes.iterrows():
        if summary['calls'] >= budget:
            summary['budget_exhausted'] = True
            logger.warning('Call budget of %d exhausted; %d routes not refreshed',
                           budget, len(routes) - summary['routes'])
            break

        origin, destination = route['origin'], route['destination']
        nights = int(route.get('median_nights', DEFAULT_TRIP_NIGHTS) or DEFAULT_TRIP_NIGHTS)
        summary['routes'] += 1
        stored_for_route = 0
        status = 'ok'

        for lead in lead_days:
            if summary['calls'] >= budget:
                summary['budget_exhausted'] = True
                break
            departure = today + timedelta(days=int(lead))
            return_date = departure + timedelta(days=nights)
            summary['calls'] += 1
            try:
                quote = provider.search(origin, destination, departure, return_date)
            except OfflineError:
                summary['offline'] = True
                return summary
            except FareProviderError as exc:
                logger.warning('Fare lookup failed for %s-%s: %s',
                               origin, destination, exc)
                summary['errors'] += 1
                status = 'error'
                continue
            except Exception as exc:  # noqa: BLE001 - one bad route must not abort the run
                logger.exception('Unexpected error for %s-%s: %s',
                                 origin, destination, exc)
                summary['errors'] += 1
                status = 'error'
                continue

            if quote is None:
                summary['uncovered'] += 1
                if status == 'ok':
                    status = 'uncovered'
                continue
            cache.put(quote)
            stored_for_route += 1
            summary['stored'] += 1

        cache.log_attempt(origin, destination, status, stored_for_route > 0)

    logger.info('Fare refresh complete: %s', summary)
    return summary


def build_provider():
    """Returns the configured provider, or None when fares are unavailable.

    Returning None is a normal outcome, not an error: it simply means the
    forecaster runs on historical data alone.
    """
    if config.OFFLINE_MODE:
        logger.info('Offline mode enabled -- no fare provider will be created')
        return None
    if not (config.AMADEUS_CLIENT_ID and config.AMADEUS_CLIENT_SECRET):
        logger.info('No Amadeus credentials set -- fares will not be refreshed')
        return None
    from .amadeus import AmadeusFareProvider
    return AmadeusFareProvider()
