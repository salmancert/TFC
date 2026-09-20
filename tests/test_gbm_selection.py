"""Gradient boosting estimator and the automatic estimator selection.

The point of these tests is not that the tree is better -- it is that the
*selection* is trustworthy: it must adopt the tree when there is real structure
to learn, and decline it when there is not, without ever making things worse.
"""
import numpy as np
import pytest

import synthetic
from travel_cost_forecasting import data_processing as dp
from travel_cost_forecasting.gbm import GBM_MIN_OBSERVATIONS, GradientBoostedEstimator
from travel_cost_forecasting.model import TripCostForecaster, evaluate

RATES = {'CN': 80.0, 'SE': 90.0, 'PL': 85.0, 'US': 100.0, 'GB': 110.0,
         'IN': 50.0, 'SG': 120.0, 'BR': 70.0, 'DE': 95.0, 'ES': 95.0}


@pytest.fixture(scope='module')
def simple_trips():
    return dp.preprocess_data(synthetic.make_export(n_trips=900), allowance_rates=RATES)


@pytest.fixture(scope='module')
def complex_trips():
    return dp.preprocess_data(synthetic.make_complex_export(n_trips=900),
                              allowance_rates=RATES)


# -- the estimator itself --------------------------------------------------
def test_gbm_extrapolates_the_trend_beyond_the_training_range(simple_trips):
    """Trees cannot extrapolate, so the trend must be applied analytically."""
    air = simple_trips[simple_trips['air_eur'] > 0]
    estimator = GradientBoostedEstimator('air_eur').fit(
        air, annual_trend=0.06, reference_year=2023.0)

    near = estimator.estimate('SE', 'CN', 4, 2025, duration_days=6, nights=5)
    far = estimator.estimate('SE', 'CN', 4, 2027, duration_days=6, nights=5)
    assert far / near == pytest.approx(1.06 ** 2, rel=1e-6)


def test_gbm_handles_a_route_it_has_never_seen(simple_trips):
    air = simple_trips[simple_trips['air_eur'] > 0]
    estimator = GradientBoostedEstimator('air_eur').fit(air)
    value = estimator.estimate('PL', 'BR', 4, 2026, duration_days=6, nights=5)
    assert np.isfinite(value) and value > 0


def test_gbm_without_a_fit_falls_back_to_the_global_value():
    estimator = GradientBoostedEstimator('air_eur')
    assert estimator.estimate('SE', 'CN', 4, 2026) == 0.0


# -- selection behaviour ---------------------------------------------------
def test_selection_declines_the_tree_when_there_is_no_structure(simple_trips):
    """On separable data the simple, explainable model must be kept."""
    forecaster = TripCostForecaster(RATES).fit(simple_trips)
    assert forecaster.air.selection['chosen'] == 'hierarchical'
    assert forecaster.air.gbm is None


def test_selection_adopts_the_tree_when_structure_exists(complex_trips):
    forecaster = TripCostForecaster(RATES).fit(complex_trips)
    assert forecaster.air.selection['chosen'] == 'gradient boosting'
    assert forecaster.air.gbm is not None
    assert forecaster.air.estimator_name == 'gradient boosting'


def test_selection_requires_a_consistent_win_across_folds(complex_trips):
    forecaster = TripCostForecaster(RATES).fit(complex_trips)
    selection = forecaster.air.selection
    assert selection['folds'] >= 2
    assert selection['wins'] * 2 > selection['folds']
    assert selection['improvement'] > 0.03


def test_selection_declines_on_small_data(simple_trips):
    """Below the observation threshold a tree is never even tried."""
    small = dp.preprocess_data(synthetic.make_complex_export(n_trips=60),
                               allowance_rates=RATES)
    forecaster = TripCostForecaster(RATES).fit(small)
    assert forecaster.air.gbm is None
    assert str(GBM_MIN_OBSERVATIONS) in forecaster.air.selection['reason']


def test_selection_can_be_turned_off(complex_trips):
    forecaster = TripCostForecaster(RATES).fit(complex_trips, enable_gbm=False)
    assert forecaster.air.gbm is None
    assert forecaster.hotel.gbm is None


def test_allowance_is_never_handed_to_a_tree(complex_trips):
    """Per-diem is policy arithmetic and must stay exact."""
    forecaster = TripCostForecaster(RATES).fit(complex_trips)
    assert not hasattr(forecaster.allowance, 'gbm')
    result = forecaster.predict('SE', 'CN', 7, 4, 2026)
    assert result['components']['allowance']['amount'] == 80.0 * 7


# -- the guarantee that matters --------------------------------------------
def test_selection_never_makes_structured_data_worse(complex_trips):
    """With real structure present, auto-selection must beat hierarchical."""
    auto = evaluate(complex_trips, RATES, enable_gbm=True)
    hierarchical = evaluate(complex_trips, RATES, enable_gbm=False)
    assert auto['total']['mdape'] < hierarchical['total']['mdape']


def test_selection_does_not_regress_unstructured_data(simple_trips):
    """With no structure to find, auto-selection must match hierarchical exactly."""
    auto = evaluate(simple_trips, RATES, enable_gbm=True)
    hierarchical = evaluate(simple_trips, RATES, enable_gbm=False)
    assert auto['total']['mdape'] == pytest.approx(hierarchical['total']['mdape'])
    assert auto['total']['mae'] == pytest.approx(hierarchical['total']['mae'])


# -- integration -----------------------------------------------------------
def test_components_still_sum_to_the_total_with_a_tree_active(complex_trips):
    forecaster = TripCostForecaster(RATES).fit(complex_trips)
    result = forecaster.predict('SE', 'CN', 7, 4, 2026)
    assert sum(c['amount'] for c in result['components'].values()) == pytest.approx(
        result['total'])


def test_prediction_reports_which_estimator_produced_each_component(complex_trips):
    forecaster = TripCostForecaster(RATES).fit(complex_trips)
    estimators = forecaster.predict('SE', 'CN', 7, 4, 2026)['estimators']
    assert estimators['air'] == 'gradient boosting'
    assert estimators['allowance'] == 'policy'


def test_a_fitted_tree_survives_save_and_load(complex_trips, tmp_path):
    forecaster = TripCostForecaster(RATES).fit(complex_trips)
    path = forecaster.save(str(tmp_path / 'model.pkl'))
    reloaded = TripCostForecaster.load(path)
    assert reloaded.air.gbm is not None
    assert reloaded.predict('SE', 'CN', 7, 4, 2026)['total'] == pytest.approx(
        forecaster.predict('SE', 'CN', 7, 4, 2026)['total'])


def test_hotel_still_scales_linearly_with_nights_under_a_tree(complex_trips):
    """Nights multiply the nightly rate; the tree estimates the rate only."""
    forecaster = TripCostForecaster(RATES).fit(complex_trips)
    three = forecaster.predict('SE', 'CN', 3, 4, 2026)['components']['hotel']
    assert three['amount'] == pytest.approx(three['nightly_rate'] * three['nights'])
