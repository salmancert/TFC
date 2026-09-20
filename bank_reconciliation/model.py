"""The scoring model that decides how match-like a candidate pair is.

Reconciliation data almost never arrives with labels, so the scorer
bootstraps its own training set: pairs that are unambiguous on the hard
evidence (same amount, same few days, no competition) become positives,
and the pairs that *compete* with them become hard negatives.  A logistic
regression fitted on that set learns, for this particular pair of files,
how much the narrative and reference columns are actually worth relative
to the amount and the date.

If a file is too small or too ambiguous to learn anything trustworthy,
the scorer falls back to fixed, accountant-style weights instead of
inventing a model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .features import FEATURE_NAMES, heuristic_scores

LOGGER = logging.getLogger(__name__)

MIN_POSITIVES = 8
MIN_NEGATIVES = 8
MIN_CV_AUC = 0.80
# How much of the fixed heuristic is kept in the final score.  A self-trained
# model can be overconfident on pairs unlike anything it was shown, so a
# slice of the hand-tuned prior is retained as a stabiliser.
DEFAULT_PRIOR_WEIGHT = 0.25


@dataclass
class TrainingReport:
    """What happened when the scorer tried to learn from this file."""

    strategy: str = "heuristic"
    n_positives: int = 0
    n_negatives: int = 0
    cv_auc: float | None = None
    reason: str = ""
    coefficients: dict[str, float] = field(default_factory=dict)

    def summary(self) -> str:
        if self.strategy == "heuristic":
            return f"heuristic weights ({self.reason})" if self.reason else "heuristic weights"
        auc = f"{self.cv_auc:.3f}" if self.cv_auc is not None else "n/a"
        return (
            f"logistic regression on {self.n_positives} self-supervised positives / "
            f"{self.n_negatives} negatives (cv AUC {auc})"
        )


@dataclass
class PairScorer:
    """Scores candidate pairs, learned or heuristic."""

    estimator: Pipeline | None = None
    prior_weight: float = DEFAULT_PRIOR_WEIGHT
    report: TrainingReport = field(default_factory=TrainingReport)

    @property
    def is_learned(self) -> bool:
        return self.estimator is not None

    def score(self, features: np.ndarray) -> np.ndarray:
        prior = heuristic_scores(features)
        if self.estimator is None or len(features) == 0:
            return prior
        learned = self.estimator.predict_proba(features)[:, 1]
        weight = float(np.clip(self.prior_weight, 0.0, 1.0))
        return np.clip((1.0 - weight) * learned + weight * prior, 0.0, 1.0)


def derive_pseudo_labels(
    features: np.ndarray,
    pairs: np.ndarray,
    rng: np.random.Generator | None = None,
    max_negatives_per_positive: int = 6,
) -> tuple[np.ndarray, np.ndarray]:
    """Bootstrap (indices, labels) into ``features`` without human labels.

    A pair is a confident positive when the amounts agree to the cent, the
    dates fall inside the window, and neither row has any other candidate
    that also clears that bar.  Every rejected competitor of a confident
    positive becomes a hard negative, which is what stops the model from
    simply relearning "the amount matched".
    """
    if len(pairs) == 0:
        return np.empty(0, dtype=int), np.empty(0, dtype=int)

    rng = rng or np.random.default_rng(0)
    columns = {name: index for index, name in enumerate(FEATURE_NAMES)}
    strong = (
        (features[:, columns["amount_exact"]] > 0.5)
        & (features[:, columns["date_within_window"]] > 0.5)
        & (features[:, columns["sign_match"]] > 0.5)
    )

    left_strong_counts: dict[int, int] = {}
    right_strong_counts: dict[int, int] = {}
    for index in np.flatnonzero(strong):
        left, right = int(pairs[index, 0]), int(pairs[index, 1])
        left_strong_counts[left] = left_strong_counts.get(left, 0) + 1
        right_strong_counts[right] = right_strong_counts.get(right, 0) + 1

    positives: list[int] = []
    anchored_left: set[int] = set()
    anchored_right: set[int] = set()
    for index in np.flatnonzero(strong):
        left, right = int(pairs[index, 0]), int(pairs[index, 1])
        if left_strong_counts[left] == 1 and right_strong_counts[right] == 1:
            positives.append(int(index))
            anchored_left.add(left)
            anchored_right.add(right)

    if not positives:
        return np.empty(0, dtype=int), np.empty(0, dtype=int)

    positive_set = set(positives)
    hard_negatives: list[int] = []
    other_negatives: list[int] = []
    for index in range(len(pairs)):
        if index in positive_set:
            continue
        left, right = int(pairs[index, 0]), int(pairs[index, 1])
        if left in anchored_left or right in anchored_right:
            # This row is already spoken for, so this candidate is a true
            # competitor: same amount or same date, but the wrong row.
            hard_negatives.append(index)
        else:
            other_negatives.append(index)

    budget = max_negatives_per_positive * len(positives)
    negatives = hard_negatives[:budget]
    if len(negatives) < budget and other_negatives:
        remaining = budget - len(negatives)
        sample = rng.permutation(np.asarray(other_negatives))[:remaining]
        negatives.extend(int(i) for i in sample)

    indices = np.asarray(positives + negatives, dtype=int)
    labels = np.concatenate(
        [np.ones(len(positives), dtype=int), np.zeros(len(negatives), dtype=int)]
    )
    return indices, labels


def _build_estimator() -> Pipeline:
    return Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    C=1.0,
                    max_iter=2000,
                    class_weight="balanced",
                    solver="lbfgs",
                ),
            ),
        ]
    )


def _cross_val_auc(estimator: Pipeline, X: np.ndarray, y: np.ndarray) -> float | None:
    minority = int(min(np.sum(y == 0), np.sum(y == 1)))
    if minority < 2:
        return None
    splits = int(min(5, minority))
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=ConvergenceWarning)
            scores = cross_val_score(
                estimator,
                X,
                y,
                cv=StratifiedKFold(n_splits=splits, shuffle=True, random_state=0),
                scoring="roc_auc",
            )
        return float(np.mean(scores))
    except ValueError as error:  # degenerate folds
        LOGGER.debug("cross-validation failed: %s", error)
        return None


def train_scorer(
    features: np.ndarray,
    labels: np.ndarray,
    prior_weight: float = DEFAULT_PRIOR_WEIGHT,
    require_validation: bool = True,
) -> PairScorer:
    """Fit a scorer on labelled pairs, refusing the model if it does not hold up."""
    report = TrainingReport(
        n_positives=int(np.sum(labels == 1)), n_negatives=int(np.sum(labels == 0))
    )

    if report.n_positives < MIN_POSITIVES or report.n_negatives < MIN_NEGATIVES:
        report.reason = (
            f"only {report.n_positives} confident positives and "
            f"{report.n_negatives} negatives available"
        )
        return PairScorer(report=report, prior_weight=prior_weight)

    estimator = _build_estimator()
    auc = _cross_val_auc(estimator, features, labels)
    report.cv_auc = auc
    if require_validation and auc is not None and auc < MIN_CV_AUC:
        report.reason = f"cross-validated AUC {auc:.3f} below {MIN_CV_AUC:.2f}"
        return PairScorer(report=report, prior_weight=prior_weight)

    estimator.fit(features, labels)
    coefficients = dict(zip(FEATURE_NAMES, estimator.named_steps["clf"].coef_[0]))

    # Every feature is built so that "higher means more match-like".  A model
    # that mostly disagrees has fitted noise in the pseudo-labels, not signal.
    if sum(1 for value in coefficients.values() if value < 0) > len(FEATURE_NAMES) // 2:
        report.reason = "learned weights contradict the feature definitions"
        return PairScorer(report=report, prior_weight=prior_weight)

    report.strategy = "logistic_regression"
    report.coefficients = {name: float(value) for name, value in coefficients.items()}
    return PairScorer(estimator=estimator, prior_weight=prior_weight, report=report)


def train_self_supervised(
    features: np.ndarray,
    pairs: np.ndarray,
    prior_weight: float = DEFAULT_PRIOR_WEIGHT,
    random_state: int = 0,
) -> PairScorer:
    """Bootstrap labels from the file itself and fit a scorer on them."""
    indices, labels = derive_pseudo_labels(
        features, pairs, rng=np.random.default_rng(random_state)
    )
    if len(indices) == 0:
        report = TrainingReport(reason="no unambiguous anchor pairs to learn from")
        return PairScorer(report=report, prior_weight=prior_weight)
    return train_scorer(features[indices], labels, prior_weight=prior_weight)


def save_scorer(scorer: PairScorer, path: str) -> None:
    """Persist a trained scorer so it can be reused on later statements."""
    import joblib

    joblib.dump(
        {
            "estimator": scorer.estimator,
            "prior_weight": scorer.prior_weight,
            "report": scorer.report,
            "feature_names": FEATURE_NAMES,
        },
        path,
    )


def load_scorer(path: str) -> PairScorer:
    """Load a scorer saved by :func:`save_scorer`."""
    import joblib

    payload = joblib.load(path)
    if tuple(payload.get("feature_names", ())) != FEATURE_NAMES:
        raise ValueError(
            f"model at {path} was trained on a different feature set and cannot be reused"
        )
    return PairScorer(
        estimator=payload["estimator"],
        prior_weight=payload.get("prior_weight", DEFAULT_PRIOR_WEIGHT),
        report=payload.get("report", TrainingReport(strategy="loaded")),
    )
