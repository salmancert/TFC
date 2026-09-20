"""Per-component travel cost forecasting.

The previous implementation predicted one total and split it into categories
using fixed historical ratios, which meant air fare and hotel were never
actually modelled. This module forecasts each component on its own terms:

    air        route market price, anchored to live fares when available
    hotel      nightly rate for the destination x nights
    allowance  policy rate x days -- exact arithmetic, never modelled
    other      per-day incidental spend for the destination x days

Estimates are hierarchically shrunk: a route with plenty of history is trusted
on its own, a thin route falls back toward its destination country, and an
unseen route falls back to the global average. That behaves sensibly on both a
10-row sample and a full multi-year export.

All training happens locally on the SAP export. Nothing is transmitted.
"""
import logging
import math
import pickle
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from . import config
from .countries import resolve_airport

logger = logging.getLogger(__name__)

#: Pseudo-count controlling hierarchical shrinkage. A group needs roughly this
#: many observations before it is trusted over its parent level.
SHRINKAGE_K = 5.0
#: Seasonal factors are clipped to this range; travel is seasonal, not wild.
MONTH_FACTOR_BOUNDS = (0.70, 1.40)
#: Annual cost trend is clipped to a plausible band.
TREND_BOUNDS = (-0.15, 0.25)
#: A live quote may move the historical estimate by at most this ratio.
ANCHOR_RATIO_BOUNDS = (0.5, 2.0)
#: Minimum observations before a time trend is fitted at all.
MIN_POINTS_FOR_TREND = 8
#: A boosted tree must beat the hierarchical estimator by this margin on held
#: out data before it is preferred. Equal accuracy should keep the simpler,
#: explainable model rather than flipping on noise.
SELECTION_MARGIN = 0.03
#: The tree is fitted in log space, so it optimises proportional error. Chosen
#: on absolute error alone it can win on cheap trips while getting materially
#: worse on the expensive long-haul ones that dominate a travel budget. So it
#: must improve the proportional error AND not degrade absolute error by more
#: than this before it is adopted.
SELECTION_MAE_TOLERANCE = 0.05
#: Rolling-origin folds used to choose between estimators. A single split is
#: too noisy to decide on: on data that genuinely suits the simple model a tree
#: can still win one split by chance. Each fold trains on everything before a
#: cut and tests on the window after it, so the comparison stays chronological.
#: These are *inner* splits of the training set -- the evaluation holdout is
#: never touched, so model choice cannot leak from it.
SELECTION_FOLDS = ((0.55, 0.70), (0.70, 0.85), (0.85, 1.00))


def _median(values):
    values = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    return float(np.median(values)) if values else None


def _mdape(predicted, actual):
    """Median absolute percentage error, ignoring zero actuals."""
    predicted, actual = np.asarray(predicted, dtype=float), np.asarray(actual, dtype=float)
    usable = actual > 0
    if not usable.any():
        return 0.0
    return float(np.median(np.abs((predicted[usable] - actual[usable]) / actual[usable])))


def _shrink(values, fallback, k=SHRINKAGE_K):
    """Blends a group's own median toward a fallback based on sample size."""
    values = list(values)
    n = len(values)
    if n == 0 or fallback is None:
        return fallback if n == 0 else _median(values)
    own = _median(values)
    if own is None:
        return fallback
    return (n * own + k * fallback) / (n + k)


def _fit_trend(frame, value_col):
    """Estimates annual fractional cost growth via a log-linear fit.

    Fitted on route-relative values, never raw ones: routes differ in price by
    a factor of four, so a shift in which routes are flown would otherwise be
    read as cost inflation.
    """
    usable = frame[(frame[value_col] > 0) & frame['t_years'].notna()]
    if len(usable) < MIN_POINTS_FOR_TREND or usable['year'].nunique() < 2:
        return 0.0
    x = usable['t_years'].to_numpy(dtype=float)
    y = np.log(usable[value_col].to_numpy(dtype=float))
    try:
        slope = float(np.polyfit(x, y, 1)[0])
    except (np.linalg.LinAlgError, ValueError):
        return 0.0
    if not math.isfinite(slope):
        return 0.0
    return float(np.clip(math.expm1(slope), *TREND_BOUNDS))


def _fit_month_factors(frame, value_col):
    """Multiplicative seasonal factor per calendar month.

    Also fitted on route-relative values -- pooling raw amounts would measure
    which destinations are popular in August, not what August does to prices.
    """
    usable = frame[frame[value_col] > 0]
    overall = _median(usable[value_col].tolist()) if len(usable) else None
    factors = {m: 1.0 for m in range(1, 13)}
    if not overall:
        return factors
    for month, group in usable.groupby('month'):
        raw = _median(group[value_col].tolist()) / overall
        # Shrink toward 1.0 so a month with two trips cannot dominate.
        shrunk = _shrink([raw] * len(group), 1.0)
        factors[int(month)] = float(np.clip(shrunk, *MONTH_FACTOR_BOUNDS))
    return factors


class _ComponentModel:
    """Shared hierarchical route/destination/global estimator."""

    #: Name of the per-trip column this component is fitted on.
    value_col = None
    #: Label used in the breakdown shown to users.
    label = None

    def __init__(self):
        self.route_values = {}
        self.dest_values = {}
        self.global_value = 0.0
        self.month_factors = {m: 1.0 for m in range(1, 13)}
        self.annual_trend = 0.0
        self.reference_year = None
        self.n_observations = 0
        #: Set only when a boosted tree demonstrably beat the hierarchical
        #: estimator on held-out data; otherwise the simple model is used.
        self.gbm = None
        self.selection = {'chosen': 'hierarchical', 'reason': 'not evaluated'}

    @property
    def estimator_name(self):
        return 'gradient boosting' if self.gbm is not None else 'hierarchical'

    def _frame(self, trips):
        """Rows that actually carry this component's cost."""
        return trips[trips[self.value_col] > 0]

    def fit(self, trips, enable_gbm=True):
        frame = self._frame(trips)
        self.n_observations = len(frame)
        if frame.empty:
            logger.warning('%s: no historical rows with a positive value; '
                           'this component will predict 0', self.label)
            self.selection = {'chosen': 'hierarchical', 'reason': 'no data'}
            return self

        self.global_value = _median(frame[self.value_col].tolist()) or 0.0
        self.route_values = {
            route: group[self.value_col].tolist()
            for route, group in frame.groupby('route')}
        self.dest_values = {
            dest: group[self.value_col].tolist()
            for dest, group in frame.groupby('dest_country')}

        # Season and trend are estimated on each trip's value relative to its
        # own route's typical level, so that route mix cannot masquerade as
        # seasonality or inflation.
        relative = frame.copy()
        route_level = relative['route'].map(
            {route: _median(values) for route, values in self.route_values.items()})
        route_level = route_level.where(route_level > 0, self.global_value or 1.0)
        relative['_relative'] = relative[self.value_col] / route_level
        self.month_factors = _fit_month_factors(relative, '_relative')
        self.annual_trend = _fit_trend(relative, '_relative')
        self.reference_year = float(frame['year'].median())

        if enable_gbm:
            self._select_estimator(frame)
        return self

    # -- estimator selection ----------------------------------------------
    def _select_estimator(self, frame):
        """Chooses between the hierarchical estimator and a boosted tree.

        Both are fitted on the earlier part of the training data and scored on
        the later part. The tree is adopted only if it wins by a clear margin,
        because the hierarchical estimator is the more explainable of the two
        and a coin-flip difference is not worth losing that.
        """
        try:
            from .gbm import GBM_MIN_OBSERVATIONS, GradientBoostedEstimator
        except ImportError:
            self.selection = {'chosen': 'hierarchical',
                              'reason': 'scikit-learn not installed'}
            return

        if len(frame) < GBM_MIN_OBSERVATIONS:
            self.selection = {
                'chosen': 'hierarchical',
                'reason': 'only %d observations, need %d for a tree to be worth it'
                          % (len(frame), GBM_MIN_OBSERVATIONS)}
            return

        ordered = frame.sort_values('start_date')
        folds = []
        for train_end, test_end in SELECTION_FOLDS:
            cut, stop = int(len(ordered) * train_end), int(len(ordered) * test_end)
            fold_train, fold_test = ordered.iloc[:cut], ordered.iloc[cut:stop]
            if len(fold_train) < 30 or fold_test.empty:
                continue
            folds.append((fold_train, fold_test))

        if not folds:
            self.selection = {'chosen': 'hierarchical',
                              'reason': 'not enough history to compare estimators'}
            return

        improvements, mae_changes, wins = [], [], 0
        for fold_train, fold_test in folds:
            actual = fold_test[self.value_col].to_numpy(dtype=float)

            baseline = type(self)()
            baseline.fit(fold_train, enable_gbm=False)
            baseline_pred = np.array([
                baseline._unit_estimate(row['home_country'], row['dest_country'],
                                        row['month'], row['year'])[0]
                for _, row in fold_test.iterrows()])

            try:
                candidate = GradientBoostedEstimator(self.value_col, self.label).fit(
                    fold_train, annual_trend=baseline.annual_trend,
                    reference_year=baseline.reference_year)
                candidate_pred = candidate.predict_frame(fold_test)
            except Exception as exc:  # noqa: BLE001 - never block training on this
                logger.warning('%s: gradient boosting failed, keeping hierarchical (%s)',
                               self.label, exc)
                self.selection = {'chosen': 'hierarchical',
                                  'reason': 'tree failed: %s' % exc}
                return

            baseline_mdape = _mdape(baseline_pred, actual)
            candidate_mdape = _mdape(candidate_pred, actual)
            baseline_mae = float(np.mean(np.abs(baseline_pred - actual)))
            candidate_mae = float(np.mean(np.abs(candidate_pred - actual)))

            improvement = ((baseline_mdape - candidate_mdape) / baseline_mdape
                           if baseline_mdape else 0.0)
            improvements.append(improvement)
            mae_changes.append((candidate_mae - baseline_mae) / baseline_mae
                               if baseline_mae > 0 else 0.0)
            if improvement > 0:
                wins += 1

        mean_improvement = float(np.mean(improvements))
        mean_mae_change = float(np.mean(mae_changes))
        majority = wins * 2 > len(folds)

        self.selection = {
            'folds': len(folds),
            'wins': wins,
            'improvement': mean_improvement,
            'mae_change': mean_mae_change,
            'fold_improvements': [round(i, 4) for i in improvements],
        }

        if not majority:
            self.selection.update(
                chosen='hierarchical',
                reason='tree won only %d of %d folds, so the gain is not consistent'
                       % (wins, len(folds)))
        elif mean_improvement <= SELECTION_MARGIN:
            self.selection.update(
                chosen='hierarchical',
                reason='tree gained only %.1f%%, under the %.0f%% margin'
                       % (mean_improvement * 100, SELECTION_MARGIN * 100))
        elif mean_mae_change > SELECTION_MAE_TOLERANCE:
            self.selection.update(
                chosen='hierarchical',
                reason='tree improved proportional error %.1f%% but worsened '
                       'absolute error %.1f%%'
                       % (mean_improvement * 100, mean_mae_change * 100))
        else:
            # Refit the winner on the whole training set, not just the folds
            # it was chosen on.
            self.gbm = GradientBoostedEstimator(self.value_col, self.label).fit(
                frame, annual_trend=self.annual_trend,
                reference_year=self.reference_year)
            self.selection.update(
                chosen='gradient boosting',
                reason='beat hierarchical by %.1f%% proportional error across %d/%d folds'
                       % (mean_improvement * 100, wins, len(folds)))
        logger.info('%s: %s', self.label, self.selection['reason'])

    def base_estimate(self, home_country, dest_country):
        """Hierarchically shrunk estimate before season and trend.

        Returns:
            (value, level, n) where level names the evidence actually used.
        """
        if self.n_observations == 0:
            return 0.0, 'none', 0

        dest_obs = self.dest_values.get(dest_country, [])
        dest_estimate = _shrink(dest_obs, self.global_value)

        route = '%s-%s' % (home_country, dest_country)
        route_obs = self.route_values.get(route, [])
        if route_obs:
            return _shrink(route_obs, dest_estimate), 'route', len(route_obs)
        if dest_obs:
            return dest_estimate, 'destination', len(dest_obs)
        return self.global_value, 'global', 0

    def seasonal_trend_multiplier(self, month, year):
        month_factor = self.month_factors.get(int(month), 1.0)
        trend_factor = 1.0
        if self.reference_year is not None and self.annual_trend:
            years_ahead = float(year) - self.reference_year
            trend_factor = (1.0 + self.annual_trend) ** years_ahead
        return month_factor * trend_factor

    def _unit_estimate(self, home_country, dest_country, month, year):
        """Hierarchical estimate of one unit of this component."""
        base, level, n = self.base_estimate(home_country, dest_country)
        return base * self.seasonal_trend_multiplier(month, year), level, n

    def _estimate(self, home_country, dest_country, month, year,
                  duration_days=1, nights=0):
        """Estimate from whichever model won selection."""
        if self.gbm is not None:
            value = self.gbm.estimate(home_country, dest_country, month, year,
                                      duration_days=duration_days, nights=nights)
            return value, 'gradient boosting', self.gbm.n_observations
        return self._unit_estimate(home_country, dest_country, month, year)

    def predict(self, home_country, dest_country, month, year,
                duration_days=1, nights=0, **kwargs):
        value, level, n = self._estimate(home_country, dest_country, month, year,
                                         duration_days, nights)
        return {'amount': max(0.0, float(value)), 'basis': level,
                'observations': n, 'source': 'historical',
                'estimator': self.estimator_name}


class AirfareModel(_ComponentModel):
    """Air ticket cost, optionally re-anchored to live market fares.

    The historical model knows what the company *used to pay* on a route. A
    live quote knows what the market charges *now*. Neither alone is right:
    history carries the corporate booking pattern, the live quote carries
    current pricing. So the live quote is applied as a ratio adjustment to the
    historical estimate, weighted by how fresh and well-sampled it is.
    """

    value_col = 'air_eur'
    label = 'Air Ticket'

    def predict(self, home_country, dest_country, month, year,
                duration_days=1, nights=0, fare_cache=None, **kwargs):
        value, level, n = self._estimate(home_country, dest_country, month, year,
                                         duration_days, nights)
        historical = max(0.0, float(value))

        result = {'amount': historical, 'basis': level, 'observations': n,
                  'source': 'historical', 'historical_amount': historical,
                  'live_price': None, 'anchor_weight': 0.0,
                  'fare_age_days': None, 'fare_quotes': 0,
                  'estimator': self.estimator_name}

        if fare_cache is None or home_country == dest_country:
            return result

        origin = resolve_airport(home_country)
        destination = resolve_airport(dest_country)
        if not origin or not destination or origin == destination:
            return result

        live_price, n_quotes, age_days = fare_cache.market_price(
            origin, destination, max_age_days=config.FARE_MAX_AGE_DAYS)
        if live_price is None or live_price <= 0:
            return result

        result.update({'live_price': float(live_price), 'fare_quotes': n_quotes,
                       'fare_age_days': age_days, 'route': '%s-%s' % (origin, destination)})

        # Freshness and sample size decide how much the live quote is trusted.
        freshness = max(0.0, 1.0 - (age_days or 0.0) / float(config.FARE_MAX_AGE_DAYS))
        coverage = n_quotes / (n_quotes + 2.0)
        weight = config.FARE_MAX_ANCHOR_WEIGHT * freshness * coverage

        if historical <= 0 or level in ('global', 'none'):
            # No meaningful route history: the live quote is the better
            # estimate, so let it lead rather than diluting it with a global
            # average that describes a different route entirely.
            weight = max(weight, 0.85 * freshness)
            anchored = live_price * weight + historical * (1.0 - weight)
        else:
            ratio = float(np.clip(live_price / historical, *ANCHOR_RATIO_BOUNDS))
            anchored = historical * (1.0 + weight * (ratio - 1.0))

        result['amount'] = max(0.0, float(anchored))
        result['anchor_weight'] = round(float(weight), 3)
        result['source'] = 'live-anchored' if weight > 0.01 else 'historical'
        return result


class HotelModel(_ComponentModel):
    """Accommodation, modelled as a nightly rate multiplied by nights."""

    value_col = 'hotel_nightly'
    label = 'Accommodation'

    def _frame(self, trips):
        return trips[(trips['hotel_eur'] > 0) & (trips['nights'] > 0)]

    def fit(self, trips, enable_gbm=True):
        trips = trips.copy()
        with np.errstate(divide='ignore', invalid='ignore'):
            trips['hotel_nightly'] = np.where(
                trips['nights'] > 0, trips['hotel_eur'] / trips['nights'].replace(0, np.nan), 0.0)
        trips['hotel_nightly'] = trips['hotel_nightly'].fillna(0.0)
        return super().fit(trips, enable_gbm=enable_gbm)

    def predict(self, home_country, dest_country, month, year, nights=0,
                duration_days=None, **kwargs):
        duration_days = nights + 1 if duration_days is None else duration_days
        nightly = super().predict(home_country, dest_country, month, year,
                                  duration_days=duration_days, nights=nights)
        nightly_rate = nightly['amount']
        nightly.update({
            'amount': max(0.0, nightly_rate * max(0, int(nights))),
            'nightly_rate': nightly_rate,
            'nights': max(0, int(nights)),
        })
        return nightly


class OtherModel(_ComponentModel):
    """Taxis, fuel, meals and everything else, as per-day spend."""

    value_col = 'other_per_day'
    label = 'Other'

    def _frame(self, trips):
        return trips[(trips['other_eur'] > 0) & (trips['duration_days'] > 0)]

    def fit(self, trips, enable_gbm=True):
        trips = trips.copy()
        trips['other_per_day'] = np.where(
            trips['duration_days'] > 0,
            trips['other_eur'] / trips['duration_days'].replace(0, np.nan), 0.0)
        trips['other_per_day'] = trips['other_per_day'].fillna(0.0)
        return super().fit(trips, enable_gbm=enable_gbm)

    def predict(self, home_country, dest_country, month, year, days=0, **kwargs):
        per_day = super().predict(home_country, dest_country, month, year,
                                  duration_days=days, nights=max(0, days - 1))
        rate = per_day['amount']
        per_day.update({
            'amount': max(0.0, rate * max(0, int(days))),
            'daily_rate': rate,
            'days': max(0, int(days)),
        })
        return per_day


class AllowanceModel:
    """Per-diem. Policy arithmetic, deliberately not a statistical model."""

    label = 'Daily Allowance'

    def __init__(self, rates=None, basis=None):
        self.rates = dict(rates or {})
        self.basis = basis or config.ALLOWANCE_BASIS
        self.median_rate = (float(np.median(list(self.rates.values())))
                            if self.rates else 0.0)

    def fit(self, trips=None):
        return self

    def predict(self, home_country, dest_country, month=None, year=None, days=0, **kwargs):
        country = home_country if self.basis == 'home' else dest_country
        known = country in self.rates
        rate = float(self.rates.get(country, self.median_rate))
        days = max(0, int(days))
        return {
            'amount': rate * days,
            'basis': 'policy rate (%s)' % country if known else 'policy median',
            'observations': None,
            'source': 'policy',
            'estimator': 'policy',
            'daily_rate': rate,
            'days': days,
            'rate_country': country,
        }


class TripCostForecaster:
    """Sums the four components into a trip estimate with full provenance."""

    def __init__(self, allowance_rates=None, allowance_basis=None):
        self.air = AirfareModel()
        self.hotel = HotelModel()
        self.other = OtherModel()
        self.allowance = AllowanceModel(allowance_rates, allowance_basis)
        self.trained_at = None
        self.n_trips = 0
        self.date_range = (None, None)

    def fit(self, trips, enable_gbm=True):
        """Fits every component, selecting an estimator per component.

        Set enable_gbm=False to force the hierarchical estimator everywhere,
        for example to compare the two directly.
        """
        self.air.fit(trips, enable_gbm=enable_gbm)
        self.hotel.fit(trips, enable_gbm=enable_gbm)
        self.other.fit(trips, enable_gbm=enable_gbm)
        self.allowance.fit(trips)
        self.n_trips = len(trips)
        if len(trips):
            self.date_range = (trips['start_date'].min(), trips['start_date'].max())
        self.trained_at = datetime.now(timezone.utc)
        return self

    def predict(self, home_country, dest_country, num_days, month, year,
                fare_cache=None):
        """Forecasts one trip.

        Args:
            num_days: Trip length in inclusive calendar days (1 = same day).

        Returns:
            A dict with `total`, a per-component `breakdown` and the evidence
            behind each figure.
        """
        num_days = max(1, int(num_days))
        nights = max(0, num_days - 1)

        components = {
            'air': self.air.predict(home_country, dest_country, month, year,
                                    duration_days=num_days, nights=nights,
                                    fare_cache=fare_cache),
            'hotel': self.hotel.predict(home_country, dest_country, month, year,
                                        nights=nights, duration_days=num_days),
            'allowance': self.allowance.predict(home_country, dest_country, month,
                                                year, days=num_days),
            'other': self.other.predict(home_country, dest_country, month, year,
                                        days=num_days),
        }
        total = sum(c['amount'] for c in components.values())

        labels = {'air': AirfareModel.label, 'hotel': HotelModel.label,
                  'allowance': AllowanceModel.label, 'other': OtherModel.label}
        breakdown = {labels[k]: v['amount'] for k, v in components.items()}

        return {
            'total': float(total),
            'breakdown': breakdown,
            'components': components,
            'inputs': {'home_country': home_country, 'dest_country': dest_country,
                       'num_days': num_days, 'nights': nights,
                       'month': int(month), 'year': int(year)},
            'fares_live': components['air']['source'] == 'live-anchored',
            'estimators': {name: component.get('estimator', 'hierarchical')
                           for name, component in components.items()},
        }

    # -- persistence -------------------------------------------------------
    def save(self, path=None):
        path = path or config.MODEL_CACHE_PATH
        import os
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'wb') as handle:
            pickle.dump(self, handle)
        return path

    @staticmethod
    def load(path=None):
        path = path or config.MODEL_CACHE_PATH
        with open(path, 'rb') as handle:
            return pickle.load(handle)


def evaluate(trips, allowance_rates, test_fraction=0.2, fare_cache=None,
             enable_gbm=True):
    """Backtests on a time-ordered holdout and reports per-component error.

    The split is chronological, never random: a random split would let the
    model learn from trips that happen after the ones it is scored on.
    """
    trips = trips.sort_values('start_date').reset_index(drop=True)
    if len(trips) < 5:
        return {'error': 'Not enough trips to evaluate (need at least 5, got %d)'
                         % len(trips)}

    split = int(len(trips) * (1.0 - test_fraction))
    train, test = trips.iloc[:split], trips.iloc[split:]
    if train.empty or test.empty:
        return {'error': 'Chronological split produced an empty side'}

    forecaster = TripCostForecaster(allowance_rates).fit(train, enable_gbm=enable_gbm)

    rows = []
    for _, trip in test.iterrows():
        prediction = forecaster.predict(
            trip['home_country'], trip['dest_country'], int(trip['duration_days']),
            int(trip['month']), int(trip['year']), fare_cache=fare_cache)
        actual_total = (trip['air_eur'] + trip['hotel_eur']
                        + trip['allowance_eur'] + trip['other_eur'])
        rows.append({
            'air_pred': prediction['components']['air']['amount'],
            'air_actual': trip['air_eur'],
            'hotel_pred': prediction['components']['hotel']['amount'],
            'hotel_actual': trip['hotel_eur'],
            'other_pred': prediction['components']['other']['amount'],
            'other_actual': trip['other_eur'],
            'total_pred': prediction['total'],
            'total_actual': actual_total,
        })

    results = pd.DataFrame(rows)
    metrics = {'n_train': len(train), 'n_test': len(test),
               'estimators': {
                   'air': forecaster.air.selection,
                   'hotel': forecaster.hotel.selection,
                   'other': forecaster.other.selection,
               }}
    for component in ('air', 'hotel', 'other', 'total'):
        error = results['%s_pred' % component] - results['%s_actual' % component]
        actual = results['%s_actual' % component]
        metrics[component] = {
            'mae': float(np.mean(np.abs(error))),
            'rmse': float(np.sqrt(np.mean(error ** 2))),
            'mean_actual': float(actual.mean()),
            # Median absolute percentage error, ignoring zero actuals, which
            # are uninformative and would otherwise divide by zero.
            'mdape': (float(np.median(np.abs(error[actual > 0] / actual[actual > 0]))) * 100
                      if (actual > 0).any() else None),
        }
    return metrics


def train_forecaster(travel_data_path=None, allowance_path=None, save=True):
    """Loads local data, fits the forecaster and optionally caches it."""
    from .data_processing import load_daily_allowance, load_travel_data, preprocess_data

    travel_data = load_travel_data(travel_data_path)
    allowance_rates = load_daily_allowance(allowance_path)
    trips = preprocess_data(travel_data, allowance_rates=allowance_rates)
    forecaster = TripCostForecaster(allowance_rates).fit(trips)
    if save:
        forecaster.save()
    return forecaster, trips, allowance_rates
