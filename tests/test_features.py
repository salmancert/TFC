"""Pairwise features: the evidence the scorer actually sees."""

import numpy as np
import pandas as pd
import pytest

from bank_reconciliation.features import (
    FEATURE_NAMES,
    TextSimilarity,
    build_feature_matrix,
)
from bank_reconciliation.schema import normalize_table


def tables(bank_rows, ledger_rows):
    columns = ["Date", "Description", "Amount"]
    left = normalize_table(pd.DataFrame(bank_rows, columns=columns), "bank")
    right = normalize_table(pd.DataFrame(ledger_rows, columns=columns), "ledger")
    return left, right


def features_for(bank_rows, ledger_rows, pairs=((0, 0),), **kwargs):
    left, right = tables(bank_rows, ledger_rows)
    similarity = TextSimilarity.fit(left.text.tolist(), right.text.tolist())
    matrix = build_feature_matrix(
        left, right, np.array(pairs), similarity, **kwargs
    )
    return {name: matrix[0, index] for index, name in enumerate(FEATURE_NAMES)}


def test_identical_rows_score_at_the_top_of_every_feature():
    row = [["2024-01-02", "ACH DEBIT NORTHWIND TRADERS INV-2001", -1500.00]]
    values = features_for(row, [["2024-01-02", "Northwind Traders INV-2001", -1500.00]])
    assert values["amount_exact"] == 1.0
    assert values["sign_match"] == 1.0
    assert values["date_proximity"] == pytest.approx(1.0)
    assert values["date_within_window"] == 1.0
    assert values["reference_overlap"] == 1.0
    assert values["token_jaccard"] > 0
    assert values["text_cosine"] > 0


def test_amount_tolerance_is_relative_to_the_transaction_size():
    """Five cents is noise on a wire transfer and a red flag on a coffee."""
    big = features_for(
        [["2024-01-02", "WIRE OUT", -50000.00]],
        [["2024-01-02", "Wire", -50000.05]],
    )
    small = features_for(
        [["2024-01-02", "COFFEE", -4.00]],
        [["2024-01-02", "Coffee", -4.05]],
    )
    assert big["amount_close"] > small["amount_close"]


def test_date_proximity_decays_with_distance():
    near = features_for(
        [["2024-01-02", "ACH NORTHWIND", -100.0]],
        [["2024-01-03", "Northwind", -100.0]],
    )
    far = features_for(
        [["2024-01-02", "ACH NORTHWIND", -100.0]],
        [["2024-03-15", "Northwind", -100.0]],
    )
    assert near["date_proximity"] > far["date_proximity"]
    assert near["date_within_window"] == 1.0
    assert far["date_within_window"] == 0.0


def test_missing_dates_are_flagged_rather_than_guessed():
    values = features_for(
        [["", "ACH NORTHWIND", -100.0]],
        [["2024-01-03", "Northwind", -100.0]],
    )
    assert values["date_known"] == 0.0
    assert values["date_proximity"] == 0.0
    assert values["amount_exact"] == 1.0  # the amount evidence still stands


def test_opposite_signs_are_reported():
    values = features_for(
        [["2024-01-02", "ACH NORTHWIND", -100.0]],
        [["2024-01-02", "Northwind", 100.0]],
    )
    assert values["sign_match"] == 0.0
    assert values["amount_exact"] == 0.0


def test_all_features_stay_within_zero_and_one():
    left, right = tables(
        [["2024-01-02", "ACH DEBIT NORTHWIND", -1500.0],
         ["2024-02-11", "CARD PURCHASE LITWARE", -75.5]],
        [["2024-01-03", "Northwind payment", -1500.0],
         ["2024-06-01", "Unrelated accrual", 9999.0]],
    )
    similarity = TextSimilarity.fit(left.text.tolist(), right.text.tolist())
    pairs = np.array([[i, j] for i in range(2) for j in range(2)])
    matrix = build_feature_matrix(left, right, pairs, similarity)
    assert matrix.shape == (4, len(FEATURE_NAMES))
    assert np.all((matrix >= 0.0) & (matrix <= 1.0))


def test_no_pairs_gives_an_empty_matrix_of_the_right_width():
    left, right = tables([["2024-01-02", "a", -1.0]], [["2024-01-02", "b", -1.0]])
    similarity = TextSimilarity.fit(left.text.tolist(), right.text.tolist())
    matrix = build_feature_matrix(left, right, np.empty((0, 2), dtype=int), similarity)
    assert matrix.shape == (0, len(FEATURE_NAMES))


def test_text_similarity_survives_empty_descriptions():
    similarity = TextSimilarity.fit(["", ""], ["", ""])
    assert similarity.similarity(np.array([0]), np.array([0])).tolist() == [0.0]
