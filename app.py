"""Flask front end for local travel cost forecasting.

Runs entirely on the machine it is started on. The expense export, the
allowance sheet, the trained model and the fare cache never leave it.
"""
import calendar
import logging
import os
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from travel_cost_forecasting import config
from travel_cost_forecasting.countries import ALL_COUNTRIES, COUNTRY_CODES
from travel_cost_forecasting.fares import FareCache
from travel_cost_forecasting.model import TripCostForecaster, train_forecaster

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)

MONTH_NAMES = list(calendar.month_name)[1:]


class ModelNotBuiltError(RuntimeError):
    """Raised when no prebuilt model is available and training is not allowed."""


def _load_forecaster(retrain=False, allow_training=None):
    """Loads the prebuilt model, training only when explicitly permitted.

    Training is deliberately not something a web worker does. On a full export
    it takes tens of seconds and a few hundred megabytes, and a server runs
    several workers -- each would train its own copy on every restart. Build
    the model once with `python cli.py train` and let the workers load it.
    """
    allow_training = config.TRAIN_ON_STARTUP if allow_training is None else allow_training

    if not retrain and os.path.exists(config.MODEL_CACHE_PATH):
        try:
            forecaster = TripCostForecaster.load()
            logger.info('Loaded model trained on %d trips (built %s)',
                        forecaster.n_trips, forecaster.trained_at)
            return forecaster
        except Exception:  # noqa: BLE001 - a stale pickle must not block startup
            logger.exception('Cached model at %s could not be loaded',
                             config.MODEL_CACHE_PATH)
            if not allow_training:
                raise ModelNotBuiltError(
                    'The model file at %s exists but could not be read. Rebuild '
                    'it with: python cli.py train' % config.MODEL_CACHE_PATH)

    if not allow_training:
        raise ModelNotBuiltError(
            'No trained model found at %s. Build one before starting the server:\n'
            '    python cli.py train\n'
            'Set TCF_TRAIN_ON_STARTUP=1 to train in-process instead, which is '
            'only appropriate for single-process local use.' % config.MODEL_CACHE_PATH)

    logger.info('Training forecaster from local data (TCF_TRAIN_ON_STARTUP is set)...')
    forecaster, _, _ = train_forecaster()
    logger.info('Training complete on %d trips', forecaster.n_trips)
    return forecaster


def create_app(retrain=False, forecaster=None, fare_cache=None,
               allow_training=None):
    app = Flask(__name__,
                template_folder='travel_cost_forecasting/templates',
                static_folder='travel_cost_forecasting/static')

    app.forecaster = forecaster or _load_forecaster(retrain=retrain,
                                                    allow_training=allow_training)
    app.fare_cache = fare_cache or FareCache(config.FARE_CACHE_PATH)

    def _context(**extra):
        stats = app.fare_cache.stats()
        trained_from, trained_to = app.forecaster.date_range
        context = {
            'countries': ALL_COUNTRIES,
            'country_names': COUNTRY_CODES,
            'months': MONTH_NAMES,
            'current_year': datetime.now().year,
            'fare_stats': stats,
            'offline_mode': config.OFFLINE_MODE,
            'fares_configured': bool(config.AMADEUS_CLIENT_ID
                                     and config.AMADEUS_CLIENT_SECRET),
            'model_info': {
                'n_trips': app.forecaster.n_trips,
                'trained_at': app.forecaster.trained_at,
                'data_from': trained_from,
                'data_to': trained_to,
            },
        }
        context.update(extra)
        return context

    def _read_request(form):
        """Validates and normalises the forecast form."""
        home = (form.get('home_country') or '').strip().upper()
        dest = (form.get('dest_country') or '').strip().upper()
        if home not in COUNTRY_CODES or dest not in COUNTRY_CODES:
            raise ValueError('Please choose a valid home and destination country.')
        try:
            num_days = int(form.get('num_days', 0))
            month = int(form.get('month', 0))
            year = int(form.get('year', datetime.now().year))
        except (TypeError, ValueError):
            raise ValueError('Duration, month and year must be whole numbers.')
        if not 1 <= num_days <= 365:
            raise ValueError('Duration must be between 1 and 365 days.')
        if not 1 <= month <= 12:
            raise ValueError('Month must be between 1 and 12.')
        if not 2000 <= year <= 2100:
            raise ValueError('Year looks out of range.')
        return home, dest, num_days, month, year

    @app.route('/')
    def index():
        return render_template('index.html', **_context())

    @app.route('/predict', methods=['POST'])
    def predict():
        try:
            home, dest, num_days, month, year = _read_request(request.form)
        except ValueError as exc:
            return render_template('index.html', **_context(error=str(exc))), 400

        result = app.forecaster.predict(home, dest, num_days, month, year,
                                        fare_cache=app.fare_cache)
        return render_template('index.html', **_context(
            result=result,
            selected={'home_country': home, 'dest_country': dest,
                      'num_days': num_days, 'month': month, 'year': year}))

    @app.route('/api/forecast', methods=['POST'])
    def api_forecast():
        """JSON endpoint, for embedding the estimate in another internal tool."""
        payload = request.get_json(silent=True) or request.form
        try:
            home, dest, num_days, month, year = _read_request(payload)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        result = app.forecaster.predict(home, dest, num_days, month, year,
                                        fare_cache=app.fare_cache)
        return jsonify(result)

    @app.route('/healthz')
    def healthz():
        """Liveness plus enough provenance to spot a stale deployment."""
        stats = app.fare_cache.stats()
        trained_at = app.forecaster.trained_at
        return jsonify({
            'status': 'ok',
            'trips': app.forecaster.n_trips,
            'model_trained_at': trained_at.isoformat() if trained_at else None,
            'fare_quotes': stats['quotes'],
            'fare_last_refresh': (stats['last_refresh'].isoformat()
                                  if stats['last_refresh'] else None),
            'offline_mode': config.OFFLINE_MODE,
        })

    return app


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Travel Cost Forecasting web app')
    parser.add_argument('--retrain', action='store_true',
                        help='Retrain from the local data instead of using the cached model.')
    parser.add_argument('--host', default='127.0.0.1',
                        help='Bind address. Defaults to localhost only.')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--debug', action='store_true',
                        help='Enable the Flask debugger. Never use on a shared host.')
    args = parser.parse_args()

    # Running this file directly is the single-process development path, so
    # training in-process is allowed here. Production serving goes through
    # wsgi.py, which does not train. See DEPLOYMENT.md.
    if args.host != '127.0.0.1':
        logger.warning('Binding to %s exposes this app to the network. It has no '
                       'authentication -- keep it on an internal interface.', args.host)
    create_app(retrain=args.retrain, allow_training=True).run(
        host=args.host, port=args.port, debug=args.debug)
