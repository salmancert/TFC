"""Gradient boosted estimator, offered as an alternative to the hierarchical one.

Where the hierarchical estimator assumes cost is separable -- route level times
a season factor times a trend -- a boosted tree can learn interactions between
those things: a nightly rate that falls on long stays, a destination whose peak
season differs from everywhere else, a duration effect that is not linear.

Whether that extra flexibility actually helps depends entirely on whether such
structure exists in the data, which is why `selection.py` fits both and lets a
held-out split decide rather than assuming.

One thing trees cannot do is extrapolate. Asked about 2027 having seen data to
2025, a tree returns whatever it learned for its latest time bucket -- it would
predict the future at today's prices. So the explicit annual trend is divided
out before fitting and multiplied back in afterwards: the tree learns route,
season and interaction structure, while trend extrapolation stays analytic.
"""
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

#: Below this many observations a boosted tree has nothing to learn that the
#: hierarchical estimator does not already capture, and will simply overfit.
GBM_MIN_OBSERVATIONS = 150

CATEGORICAL_FEATURES = ['home_country', 'dest_country', 'route']
NUMERIC_FEATURES = ['month', 'duration_days', 'nights', 'is_international']


class GradientBoostedEstimator:
    """Predicts a component's value from route, season and trip shape."""

    def __init__(self, value_col, label=None, random_state=0):
        self.value_col = value_col
        self.label = label or value_col
        self.random_state = random_state
        self.model = None
        self.categories = {}
        self.annual_trend = 0.0
        self.reference_year = None
        self.n_observations = 0
        self.global_value = 0.0

    # -- feature construction ---------------------------------------------
    def _encode(self, frame, fit=False):
        """Builds the design matrix, encoding categoricals as integer codes.

        Unseen categories become NaN, which HistGradientBoostingRegressor
        handles natively as missing rather than failing.
        """
        columns = {}
        for name in CATEGORICAL_FEATURES:
            values = frame[name].astype(str)
            if fit:
                self.categories[name] = {v: i for i, v in enumerate(sorted(values.unique()))}
            mapping = self.categories.get(name, {})
            columns[name] = values.map(mapping).astype(float)
        for name in NUMERIC_FEATURES:
            columns[name] = frame[name].astype(float)
        return pd.DataFrame(columns, index=frame.index)

    def _detrend(self, frame):
        """Removes the analytic time trend so the tree never has to extrapolate."""
        if not self.annual_trend or self.reference_year is None:
            return np.ones(len(frame))
        years_ahead = frame['year'].astype(float) - self.reference_year
        return np.power(1.0 + self.annual_trend, years_ahead)

    # -- fitting -----------------------------------------------------------
    def fit(self, frame, annual_trend=0.0, reference_year=None):
        """Fits on rows already filtered to those carrying this component.

        Args:
            frame: Trip rows with `value_col` populated and positive.
            annual_trend: Trend estimated analytically by the hierarchical
                model, divided out here and re-applied at prediction time.
            reference_year: The year that trend is anchored to.
        """
        from sklearn.ensemble import HistGradientBoostingRegressor

        self.n_observations = len(frame)
        if frame.empty:
            return self
        self.annual_trend = annual_trend
        self.reference_year = reference_year
        self.global_value = float(np.median(frame[self.value_col]))

        features = self._encode(frame, fit=True)
        target = frame[self.value_col].to_numpy(dtype=float) / self._detrend(frame)
        # Costs are positive and multiplicative, so errors are proportional;
        # fitting in log space keeps a long-haul fare from dominating the loss.
        target = np.log1p(np.clip(target, 0.0, None))

        categorical_mask = [name in CATEGORICAL_FEATURES for name in features.columns]
        self.model = HistGradientBoostingRegressor(
            max_iter=300,
            learning_rate=0.06,
            max_leaf_nodes=15,
            min_samples_leaf=10,
            l2_regularization=1.0,
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=25,
            categorical_features=categorical_mask,
            random_state=self.random_state,
        )
        self.model.fit(features, target)
        return self

    # -- prediction --------------------------------------------------------
    def predict_frame(self, frame):
        """Vectorised prediction for a frame of trips."""
        if self.model is None or frame.empty:
            return np.full(len(frame), self.global_value, dtype=float)
        features = self._encode(frame, fit=False)
        detrended = np.expm1(self.model.predict(features))
        return np.clip(detrended, 0.0, None) * self._detrend(frame)

    def estimate(self, home_country, dest_country, month, year,
                 duration_days=1, nights=0):
        """Single-trip estimate, matching the hierarchical estimator's contract."""
        if self.model is None:
            return self.global_value
        frame = pd.DataFrame([{
            'home_country': home_country,
            'dest_country': dest_country,
            'route': '%s-%s' % (home_country, dest_country),
            'month': int(month),
            'year': int(year),
            'duration_days': int(duration_days),
            'nights': int(nights),
            'is_international': float(home_country != dest_country),
        }])
        return float(self.predict_frame(frame)[0])
