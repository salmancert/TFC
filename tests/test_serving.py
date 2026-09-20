"""Serving-path guarantees that matter once other people depend on this."""
import pytest

import synthetic
from app import ModelNotBuiltError, create_app, _load_forecaster
from travel_cost_forecasting import config
from travel_cost_forecasting import data_processing as dp
from travel_cost_forecasting.fares import FareCache
from travel_cost_forecasting.model import TripCostForecaster

RATES = {'CN': 80.0, 'SE': 90.0, 'PL': 85.0, 'US': 100.0, 'GB': 110.0,
         'IN': 50.0, 'SG': 120.0, 'BR': 70.0, 'DE': 95.0, 'ES': 95.0}


@pytest.fixture
def built_model(tmp_path, monkeypatch):
    """A model file on disk, as `cli.py train` would leave it."""
    trips = dp.preprocess_data(synthetic.make_export(n_trips=120),
                               allowance_rates=RATES)
    path = str(tmp_path / 'forecaster.pkl')
    TripCostForecaster(RATES).fit(trips).save(path)
    monkeypatch.setattr(config, 'MODEL_CACHE_PATH', path)
    return path


def test_serving_refuses_to_train_when_no_model_exists(tmp_path, monkeypatch):
    """A web worker must never kick off a 30-second training run."""
    monkeypatch.setattr(config, 'MODEL_CACHE_PATH', str(tmp_path / 'missing.pkl'))
    monkeypatch.setattr(config, 'TRAIN_ON_STARTUP', False)
    with pytest.raises(ModelNotBuiltError) as excinfo:
        _load_forecaster(allow_training=False)
    # The message has to tell an operator what to actually do.
    assert 'cli.py train' in str(excinfo.value)


def test_serving_refuses_on_an_unreadable_model(tmp_path, monkeypatch):
    """A truncated or version-mismatched pickle must fail, not serve nonsense."""
    corrupt = tmp_path / 'forecaster.pkl'
    corrupt.write_bytes(b'not a pickle')
    monkeypatch.setattr(config, 'MODEL_CACHE_PATH', str(corrupt))
    with pytest.raises(ModelNotBuiltError):
        _load_forecaster(allow_training=False)


def test_serving_loads_a_prebuilt_model(built_model):
    forecaster = _load_forecaster(allow_training=False)
    assert forecaster.n_trips == 120


def test_training_still_allowed_when_explicitly_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'MODEL_CACHE_PATH', str(tmp_path / 'missing.pkl'))
    monkeypatch.setattr(config, 'TRAIN_ON_STARTUP', True)
    # No model file, but training is permitted, so this must not raise.
    assert _load_forecaster().n_trips > 0


def test_healthz_exposes_provenance_for_monitoring(built_model, tmp_path):
    app = create_app(fare_cache=FareCache(str(tmp_path / 'f.sqlite3')),
                     allow_training=False)
    payload = app.test_client().get('/healthz').get_json()
    assert payload['status'] == 'ok'
    assert payload['trips'] == 120
    # These are what an operator alerts on when a scheduled job dies.
    assert 'model_trained_at' in payload
    assert 'fare_last_refresh' in payload


def test_fare_cache_allows_concurrent_readers_and_a_writer(tmp_path):
    """The refresh job writes while web workers read; WAL makes that safe."""
    path = str(tmp_path / 'fares.sqlite3')
    writer, reader = FareCache(path), FareCache(path)

    mode = writer._conn.execute('PRAGMA journal_mode').fetchone()[0]
    assert mode.lower() == 'wal'

    from datetime import date, timedelta

    from travel_cost_forecasting.fares import FareQuote
    writer.put(FareQuote(origin='ARN', destination='PVG',
                         departure_date=date.today() + timedelta(days=21),
                         price_eur=742.0, provider='test', lead_days=21))
    # A second connection sees the committed write without locking errors.
    assert reader.market_price('ARN', 'PVG')[0] == 742.0


def test_wsgi_module_exposes_a_callable(built_model, monkeypatch):
    """gunicorn and waitress both import `wsgi:application`."""
    import importlib

    import wsgi
    importlib.reload(wsgi)
    assert callable(wsgi.application)
    assert wsgi.app is wsgi.application
