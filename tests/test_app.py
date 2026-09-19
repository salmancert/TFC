"""Web layer tests: request validation and rendering."""
import pytest

import synthetic
from app import create_app
from travel_cost_forecasting import data_processing as dp
from travel_cost_forecasting.fares import FareCache
from travel_cost_forecasting.model import TripCostForecaster

RATES = {'CN': 80.0, 'SE': 90.0, 'PL': 85.0, 'US': 100.0, 'GB': 110.0,
         'IN': 50.0, 'SG': 120.0, 'BR': 70.0, 'DE': 95.0, 'ES': 95.0}


@pytest.fixture
def client(tmp_path):
    trips = dp.preprocess_data(synthetic.make_export(n_trips=200),
                               allowance_rates=RATES)
    forecaster = TripCostForecaster(RATES).fit(trips)
    cache = FareCache(str(tmp_path / 'fares.sqlite3'))
    app = create_app(forecaster=forecaster, fare_cache=cache)
    app.config.update(TESTING=True)
    return app.test_client()


def test_index_renders_the_form(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b'Trip Parameters' in response.data


def test_predict_renders_every_component(client):
    response = client.post('/predict', data={
        'home_country': 'SE', 'dest_country': 'CN',
        'num_days': '7', 'month': '4', 'year': '2026'})
    assert response.status_code == 200
    for label in (b'Air Ticket', b'Accommodation', b'Daily Allowance', b'Other'):
        assert label in response.data


def test_json_api_returns_a_full_breakdown(client):
    response = client.post('/api/forecast', json={
        'home_country': 'SE', 'dest_country': 'CN',
        'num_days': 7, 'month': 4, 'year': 2026})
    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload['components']) == {'air', 'hotel', 'allowance', 'other'}
    assert payload['total'] == pytest.approx(
        sum(c['amount'] for c in payload['components'].values()))


@pytest.mark.parametrize('payload', [
    {'home_country': 'ZZ', 'dest_country': 'CN', 'num_days': 7, 'month': 4, 'year': 2026},
    {'home_country': 'SE', 'dest_country': 'CN', 'num_days': 0, 'month': 4, 'year': 2026},
    {'home_country': 'SE', 'dest_country': 'CN', 'num_days': 7, 'month': 13, 'year': 2026},
    {'home_country': 'SE', 'dest_country': 'CN', 'num_days': 'x', 'month': 4, 'year': 2026},
    {'home_country': 'SE', 'dest_country': 'CN', 'num_days': 7, 'month': 4, 'year': 1200},
])
def test_invalid_input_is_rejected_not_crashed(client, payload):
    assert client.post('/predict', data=payload).status_code == 400
    assert client.post('/api/forecast', json=payload).status_code == 400


def test_healthcheck(client):
    response = client.get('/healthz')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'ok'
