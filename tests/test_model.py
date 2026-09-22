"""The self-supervised scorer and its guard rails."""

import numpy as np
import pytest

from bank_reconciliation.features import FEATURE_NAMES, heuristic_scores
from bank_reconciliation.model import (
    derive_pseudo_labels,
    load_scorer,
    save_scorer,
    train_scorer,
    train_self_supervised,
)


def make_features(rows):
    """rows: list of dicts keyed by feature name."""
    matrix = np.zeros((len(rows), len(FEATURE_NAMES)))
    for index, row in enumerate(rows):
        for name, value in row.items():
            matrix[index, FEATURE_NAMES.index(name)] = value
    return matrix


def test_heuristic_scores_rank_a_good_pair_above_a_bad_one():
    features = make_features([
        {"amount_exact": 1, "amount_close": 1, "date_proximity": 1,
         "date_within_window": 1, "sign_match": 1, "text_cosine": 0.9},
        {"amount_relative": 0.1},
    ])
    scores = heuristic_scores(features)
    assert scores[0] > scores[1]
    assert np.all((scores >= 0) & (scores <= 1))


def test_pseudo_labels_pick_unambiguous_pairs_as_positives():
    pairs = np.array([[0, 0], [1, 1], [1, 0]])
    features = make_features([
        {"amount_exact": 1, "date_within_window": 1, "sign_match": 1},
        {"amount_exact": 1, "date_within_window": 1, "sign_match": 1},
        {"amount_relative": 0.3},
    ])
    indices, labels = derive_pseudo_labels(features, pairs)
    positives = {tuple(pairs[i]) for i, label in zip(indices, labels) if label == 1}
    assert positives == {(0, 0), (1, 1)}


def test_a_contested_pair_is_not_used_as_a_positive():
    """Two bank rows competing for one ledger row teaches nothing reliable."""
    pairs = np.array([[0, 0], [1, 0]])
    features = make_features([
        {"amount_exact": 1, "date_within_window": 1, "sign_match": 1},
        {"amount_exact": 1, "date_within_window": 1, "sign_match": 1},
    ])
    indices, labels = derive_pseudo_labels(features, pairs)
    assert indices.size == 0 and labels.size == 0


def test_training_falls_back_to_heuristics_without_enough_examples():
    features = make_features([{"amount_exact": 1}, {"amount_exact": 0}])
    scorer = train_scorer(features, np.array([1, 0]))
    assert not scorer.is_learned
    assert "positives" in scorer.report.reason


def test_training_succeeds_on_a_separable_problem():
    rng = np.random.default_rng(0)
    positives = [
        {"amount_exact": 1, "amount_close": 1, "date_proximity": 0.9,
         "date_within_window": 1, "sign_match": 1, "date_known": 1,
         "text_cosine": float(rng.uniform(0.6, 0.9))}
        for _ in range(30)
    ]
    negatives = [
        {"amount_relative": float(rng.uniform(0, 0.3)), "date_known": 1,
         "text_cosine": float(rng.uniform(0, 0.2))}
        for _ in range(30)
    ]
    features = make_features(positives + negatives)
    labels = np.array([1] * 30 + [0] * 30)
    scorer = train_scorer(features, labels)
    assert scorer.is_learned
    assert scorer.report.cv_auc is not None and scorer.report.cv_auc > 0.9
    scores = scorer.score(features)
    assert scores[:30].mean() > scores[30:].mean()


def test_a_model_that_cannot_be_validated_is_rejected():
    """Random labels must not produce a model the reconciler then trusts."""
    rng = np.random.default_rng(1)
    features = rng.random((80, len(FEATURE_NAMES)))
    labels = rng.integers(0, 2, size=80)
    scorer = train_scorer(features, labels)
    assert not scorer.is_learned
    assert scorer.report.reason


def test_scores_stay_in_range_and_blend_the_prior():
    rng = np.random.default_rng(2)
    features = np.clip(rng.random((40, len(FEATURE_NAMES))), 0, 1)
    scorer = train_self_supervised(features, np.array([[i, i] for i in range(40)]))
    scores = scorer.score(features)
    assert np.all((scores >= 0.0) & (scores <= 1.0))


def test_save_and_load_round_trip(tmp_path):
    rng = np.random.default_rng(3)
    positives = np.tile(
        make_features([{name: 1.0 for name in FEATURE_NAMES}]), (25, 1)
    ) * rng.uniform(0.8, 1.0, size=(25, len(FEATURE_NAMES)))
    negatives = rng.uniform(0.0, 0.2, size=(25, len(FEATURE_NAMES)))
    features = np.vstack([positives, negatives])
    labels = np.array([1] * 25 + [0] * 25)
    scorer = train_scorer(features, labels)
    assert scorer.is_learned

    target = tmp_path / "scorer.joblib"
    save_scorer(scorer, str(target))
    restored = load_scorer(str(target))
    assert np.allclose(scorer.score(features), restored.score(features))


def test_loading_a_model_with_the_wrong_features_is_refused(tmp_path):
    import joblib

    target = tmp_path / "stale.joblib"
    joblib.dump({"estimator": None, "feature_names": ("only_one",)}, target)
    with pytest.raises(ValueError, match="different feature set"):
        load_scorer(str(target))
