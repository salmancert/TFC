"""Matching behaviour: uniqueness, thresholds, sign conventions, grouping."""

import numpy as np
import pandas as pd
import pytest

from bank_reconciliation import ReconciliationConfig, reconcile
from bank_reconciliation.sample_data import generate_sample


def frame(rows):
    return pd.DataFrame(rows, columns=["Date", "Description", "Amount"])


def test_obvious_pairs_are_matched():
    bank = frame([
        ["2024-01-02", "ACH DEBIT NORTHWIND", -1500.00],
        ["2024-01-05", "WIRE IN ALPINE RETAIL", 5000.00],
    ])
    ledger = frame([
        ["2024-01-03", "Payment Northwind Traders", -1500.00],
        ["2024-01-05", "Alpine Retail invoice", 5000.00],
    ])
    result = reconcile(bank, ledger, "bank", "ledger")
    pairs = {r.left_rows[0]: r.right_rows[0] for r in result.records}
    assert pairs == {0: 0, 1: 1}
    assert not result.unmatched_left and not result.unmatched_right


def test_a_ledger_row_is_never_claimed_twice():
    """The old approach let every bank row pick the same nearest neighbour."""
    bank = frame([
        ["2024-01-02", "ACH DEBIT NORTHWIND", -100.00],
        ["2024-01-02", "ACH DEBIT NORTHWIND", -100.00],
        ["2024-01-02", "ACH DEBIT NORTHWIND", -100.00],
    ])
    ledger = frame([["2024-01-02", "Northwind payment", -100.00]])
    result = reconcile(bank, ledger, "bank", "ledger")
    claimed = [row for record in result.records for row in record.right_rows]
    assert len(claimed) == len(set(claimed)) == 1
    assert len(result.unmatched_left) == 2


def test_rows_with_no_counterpart_are_reported_unmatched():
    """Every row used to be handed a 'match' regardless of quality."""
    bank = frame([["2024-01-02", "MONTHLY ACCOUNT FEE", -15.00]])
    ledger = frame([["2024-06-30", "Annual insurance premium", -8200.00]])
    result = reconcile(bank, ledger, "bank", "ledger")
    assert result.records == []
    assert result.unmatched_left == [0]
    assert result.unmatched_right == [0]


def test_text_breaks_the_tie_when_amounts_are_identical():
    bank = frame([
        ["2024-01-02", "ACH DEBIT NORTHWIND TRADERS", -250.00],
        ["2024-01-02", "ACH DEBIT CONTOSO SUPPLIES", -250.00],
    ])
    ledger = frame([
        ["2024-01-02", "Contoso Supplies invoice", -250.00],
        ["2024-01-02", "Northwind Traders payment", -250.00],
    ])
    result = reconcile(bank, ledger, "bank", "ledger")
    pairs = {r.left_rows[0]: r.right_rows[0] for r in result.records}
    assert pairs == {0: 1, 1: 0}


def test_opposite_sign_conventions_are_detected():
    bank = frame([
        ["2024-01-02", "ACH DEBIT NORTHWIND", -1500.00],
        ["2024-01-04", "ACH DEBIT CONTOSO", -900.00],
        ["2024-01-06", "CARD PURCHASE LITWARE", -75.50],
    ])
    ledger = frame([
        ["2024-01-02", "Northwind payment", 1500.00],
        ["2024-01-04", "Contoso payment", 900.00],
        ["2024-01-06", "Litware hosting", 75.50],
    ])
    result = reconcile(bank, ledger, "bank", "ledger")
    assert result.sign_flipped is True
    assert len(result.records) == 3


def test_sign_convention_can_be_forced():
    sample = generate_sample(n_matched=20, n_groups=0, seed=3)
    config = ReconciliationConfig(sign_convention="same")
    result = reconcile(sample.bank, sample.ledger, "bank", "ledger", config=config)
    assert result.sign_flipped is False


def test_one_bank_line_can_settle_several_ledger_lines():
    bank = frame([["2024-01-10", "ACH DEBIT NORTHWIND BATCH", -600.00]])
    ledger = frame([
        ["2024-01-09", "Northwind invoice A", -250.00],
        ["2024-01-10", "Northwind invoice B", -350.00],
    ])
    result = reconcile(bank, ledger, "bank", "ledger")
    assert len(result.records) == 1
    record = result.records[0]
    assert record.kind == "grouped"
    assert record.right_rows == (0, 1)


def test_group_matching_can_be_disabled():
    bank = frame([["2024-01-10", "ACH DEBIT NORTHWIND BATCH", -600.00]])
    ledger = frame([
        ["2024-01-09", "Northwind invoice A", -250.00],
        ["2024-01-10", "Northwind invoice B", -350.00],
    ])
    config = ReconciliationConfig(group_matching=False)
    result = reconcile(bank, ledger, "bank", "ledger", config=config)
    assert all(record.kind != "grouped" for record in result.records)


def test_borderline_pairs_are_flagged_for_review_not_auto_accepted():
    bank = frame([["2024-01-02", "CARD PURCHASE UNKNOWN MERCHANT", -100.00]])
    ledger = frame([["2024-01-02", "Completely different narrative", -100.40]])
    config = ReconciliationConfig(match_threshold=0.95, review_threshold=0.20)
    result = reconcile(bank, ledger, "bank", "ledger", config=config)
    assert [r.status for r in result.records] == ["review"]


def test_thresholds_are_validated():
    with pytest.raises(ValueError):
        ReconciliationConfig(match_threshold=0.3, review_threshold=0.8).validate()
    with pytest.raises(ValueError):
        ReconciliationConfig(sign_convention="sideways").validate()


def test_empty_input_is_handled():
    empty = frame([])
    result = reconcile(empty, frame([["2024-01-02", "x", -1.0]]), "bank", "ledger")
    assert result.records == []
    assert result.unmatched_right == [0]


@pytest.mark.parametrize("seed", [7, 11, 23])
def test_accuracy_on_generated_data_with_known_answers(seed):
    sample = generate_sample(seed=seed)
    result = reconcile(sample.bank, sample.ledger, "Bank", "Ledger")
    predicted = {r.left_rows[0]: tuple(sorted(r.right_rows)) for r in result.records}
    correct = sum(1 for b, l in predicted.items() if sample.truth.get(b) == l)
    precision = correct / max(len(predicted), 1)
    recall = correct / sample.n_true_pairs
    assert precision >= 0.98, f"precision {precision:.3f}"
    assert recall >= 0.95, f"recall {recall:.3f}"


def test_flipped_sign_sample_still_reconciles():
    sample = generate_sample(n_matched=40, n_groups=0, seed=5, flip_ledger_sign=True)
    result = reconcile(sample.bank, sample.ledger, "Bank", "Ledger")
    assert result.sign_flipped is True
    predicted = {r.left_rows[0]: tuple(sorted(r.right_rows)) for r in result.records}
    correct = sum(1 for b, l in predicted.items() if sample.truth.get(b) == l)
    assert correct / sample.n_true_pairs >= 0.95


def test_dates_in_day_first_format_do_not_break_matching():
    """A dd/mm/yyyy ledger against a yyyy-mm-dd statement."""
    bank = frame([["2024-03-09", "ACH DEBIT NORTHWIND", -1500.00]])
    ledger = pd.DataFrame(
        [["09/03/2024", "Northwind payment", -1500.00]],
        columns=["Entry Date", "Memo", "Net Amount"],
    )
    result = reconcile(bank, ledger, "bank", "ledger")
    assert len(result.records) == 1
    assert result.records[0].evidence["date_proximity"] == pytest.approx(1.0)
