"""Command line entry points for training, forecasting and fare refresh.

    python cli.py train --evaluate
    python cli.py forecast --home SE --dest CN --days 7 --month 4 --year 2026
    python cli.py refresh-fares --cadence daily
    python cli.py fare-status
"""
import argparse
import logging
import sys

from travel_cost_forecasting import config
from travel_cost_forecasting.countries import COUNTRY_CODES
from travel_cost_forecasting.data_processing import (load_daily_allowance,
                                                     load_travel_data,
                                                     preprocess_data)
from travel_cost_forecasting.fares import FareCache
from travel_cost_forecasting.fares import refresh as fare_refresh
from travel_cost_forecasting.model import (TripCostForecaster, evaluate,
                                           train_forecaster)

logger = logging.getLogger('tcf')


def cmd_train(args):
    forecaster, trips, rates = train_forecaster(save=True)
    print('Trained on %d trips (%s to %s)' % (
        forecaster.n_trips,
        forecaster.date_range[0].date() if forecaster.date_range[0] is not None else '?',
        forecaster.date_range[1].date() if forecaster.date_range[1] is not None else '?'))
    print('Model cached at %s' % config.MODEL_CACHE_PATH)
    print()
    print('Estimator chosen per component (decided on held-out folds):')
    for name in ('air', 'hotel', 'other'):
        component = getattr(forecaster, name)
        print('  %-6s %-18s %d obs, trend %+.1f%% -- %s'
              % (name, component.selection.get('chosen', 'hierarchical'),
                 component.n_observations, component.annual_trend * 100,
                 component.selection.get('reason', '')))

    if args.evaluate:
        print('\nChronological backtest (last %d%% held out):' % int(args.test_fraction * 100))
        metrics = evaluate(trips, rates, test_fraction=args.test_fraction)
        if 'error' in metrics:
            print('  %s' % metrics['error'])
            return 0
        print('  train=%d  test=%d' % (metrics['n_train'], metrics['n_test']))
        for component in ('air', 'hotel', 'other', 'total'):
            stats = metrics[component]
            mdape = '%.1f%%' % stats['mdape'] if stats['mdape'] is not None else 'n/a'
            print('  %-6s MAE %9.2f  RMSE %9.2f  mean actual %9.2f  MdAPE %s'
                  % (component, stats['mae'], stats['rmse'], stats['mean_actual'], mdape))
    return 0


def cmd_forecast(args):
    forecaster = TripCostForecaster.load()
    cache = FareCache(config.FARE_CACHE_PATH)
    result = forecaster.predict(args.home, args.dest, args.days, args.month,
                                args.year, fare_cache=cache)

    print('%s -> %s, %d day(s), %02d/%d'
          % (COUNTRY_CODES.get(args.home, args.home),
             COUNTRY_CODES.get(args.dest, args.dest),
             args.days, args.month, args.year))
    print('-' * 62)
    for key, component in result['components'].items():
        detail = component.get('basis', '')
        if component.get('estimator') == 'gradient boosting':
            detail = 'gradient boosting'
        if component['source'] == 'live-anchored':
            detail = 'live fare %.0f EUR, weight %.2f, %s history' % (
                component['live_price'], component['anchor_weight'], component['basis'])
        print('  %-16s %10.2f EUR   (%s)' % (key, component['amount'], detail))
    print('-' * 62)
    print('  %-16s %10.2f EUR' % ('TOTAL', result['total']))
    if not result['fares_live']:
        print('\nNote: airfare is historical only. Run "refresh-fares" with '
              'Amadeus credentials set for live pricing.')
    return 0


def cmd_refresh(args):
    if config.OFFLINE_MODE:
        print('Offline mode is enabled (TCF_OFFLINE). No network calls will be made.')
        return 0

    travel_data = load_travel_data()
    rates = load_daily_allowance()
    trips = preprocess_data(travel_data, allowance_rates=rates)

    cache = FareCache(config.FARE_CACHE_PATH)
    ranked = fare_refresh.rank_routes(trips)
    if ranked.empty:
        print('No flyable routes found in the historical data; nothing to refresh.')
        return 0

    selected = fare_refresh.select_routes(ranked, cache, cadence=args.cadence,
                                          top_n=args.top_n, batch=args.batch)
    print('%s run: %d route(s) selected out of %d known, %d lead time(s) each'
          % (args.cadence, len(selected), len(ranked), len(config.FARE_LEAD_DAYS)))

    if args.dry_run:
        for _, route in selected.iterrows():
            print('  %s-%s  (%s-%s, %d historical trips)'
                  % (route['origin'], route['destination'], route['home_country'],
                     route['dest_country'], route['trips']))
        print('\nDry run: no API calls made. Estimated cost: %d calls.'
              % (len(selected) * len(config.FARE_LEAD_DAYS)))
        return 0

    provider = fare_refresh.build_provider()
    if provider is None:
        print('No fare provider available. Set AMADEUS_CLIENT_ID and '
              'AMADEUS_CLIENT_SECRET, or run with --dry-run to preview.')
        return 1

    try:
        summary = fare_refresh.refresh_fares(provider, cache, selected,
                                             budget=args.budget)
    finally:
        provider.close()

    print('Calls %(calls)d | stored %(stored)d | routes %(routes)d | '
          'uncovered %(uncovered)d | errors %(errors)d' % summary)
    if summary.get('budget_exhausted'):
        print('Budget exhausted -- remaining routes will be picked up next run.')
    return 0


def cmd_fare_status(args):
    cache = FareCache(config.FARE_CACHE_PATH)
    stats = cache.stats()
    print('Fare cache: %s' % config.FARE_CACHE_PATH)
    print('  quotes stored : %d' % stats['quotes'])
    print('  routes covered: %d' % stats['routes'])
    print('  last refresh  : %s' % (stats['last_refresh'] or 'never'))
    print('  offline mode  : %s' % ('ON (no network calls)' if config.OFFLINE_MODE else 'off'))
    print('  credentials   : %s' % ('set' if (config.AMADEUS_CLIENT_ID
                                              and config.AMADEUS_CLIENT_SECRET) else 'not set'))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description='Travel cost forecasting toolbox')
    parser.add_argument('-v', '--verbose', action='store_true')
    sub = parser.add_subparsers(dest='command', required=True)

    train = sub.add_parser('train', help='Train the forecaster on the local export.')
    train.add_argument('--evaluate', action='store_true',
                       help='Also run a chronological backtest.')
    train.add_argument('--test-fraction', type=float, default=0.2)
    train.set_defaults(func=cmd_train)

    forecast = sub.add_parser('forecast', help='Forecast a single trip.')
    forecast.add_argument('--home', required=True, type=str.upper)
    forecast.add_argument('--dest', required=True, type=str.upper)
    forecast.add_argument('--days', required=True, type=int)
    forecast.add_argument('--month', required=True, type=int)
    forecast.add_argument('--year', type=int, default=2026)
    forecast.set_defaults(func=cmd_forecast)

    refresh = sub.add_parser('refresh-fares', help='Fetch live fares for busy routes.')
    refresh.add_argument('--cadence', choices=('daily', 'weekly'), default='daily')
    refresh.add_argument('--top-n', type=int, default=None)
    refresh.add_argument('--batch', type=int, default=None)
    refresh.add_argument('--budget', type=int, default=None,
                         help='Maximum API calls for this run.')
    refresh.add_argument('--dry-run', action='store_true',
                         help='Show which routes would be refreshed, call nothing.')
    refresh.set_defaults(func=cmd_refresh)

    status = sub.add_parser('fare-status', help='Show fare cache freshness.')
    status.set_defaults(func=cmd_fare_status)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(levelname)s %(name)s: %(message)s')
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
