"""Column detection and value parsing."""

import numpy as np
import pandas as pd
import pytest

from bank_reconciliation.schema import (
    detect_roles,
    extract_references,
    infer_dayfirst,
    informative_tokens,
    normalize_table,
    parse_amount_series,
    parse_date_series,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1,234.56", 1234.56),
        ("$1,234.56", 1234.56),
        ("(1,234.56)", -1234.56),
        ("-15.00", -15.0),
        ("1.234,56", 1234.56),      # European grouping
        ("1234,56", 1234.56),       # European decimal comma
        ("100.00 CR", 100.0),
        ("100.00 DR", -100.0),
        ("", np.nan),
        ("n/a", np.nan),
    ],
)
def test_parse_amount_handles_real_world_formats(raw, expected):
    value = parse_amount_series(pd.Series([raw])).iloc[0]
    if np.isnan(expected):
        assert np.isnan(value)
    else:
        assert value == pytest.approx(expected)


def test_parse_amount_passes_numeric_through():
    result = parse_amount_series(pd.Series([1.5, -2.0, np.nan]))
    assert result.tolist()[:2] == [1.5, -2.0]


def test_infer_dayfirst_reads_the_convention_off_the_data():
    assert infer_dayfirst(pd.Series(["09/03/2024", "14/04/2024"])) is True
    assert infer_dayfirst(pd.Series(["03/09/2024", "12/25/2024"])) is False
    assert infer_dayfirst(pd.Series(["01/02/2024", "03/04/2024"])) is None


def test_day_first_dates_are_not_silently_shifted():
    """09/03/2024 in a dd/mm/yyyy column is 9 March, not 3 September."""
    parsed = parse_date_series(pd.Series(["09/03/2024", "14/04/2024"]))
    assert parsed.iloc[0] == pd.Timestamp("2024-03-09")
    assert parsed.iloc[1] == pd.Timestamp("2024-04-14")


def test_month_first_dates_still_parse_as_month_first():
    parsed = parse_date_series(pd.Series(["03/09/2024", "12/25/2024"]))
    assert parsed.iloc[0] == pd.Timestamp("2024-03-09")


def test_explicit_dayfirst_overrides_detection():
    parsed = parse_date_series(pd.Series(["01/02/2024"]), dayfirst=True)
    assert parsed.iloc[0] == pd.Timestamp("2024-02-01")


def test_detect_roles_on_a_typical_bank_export():
    frame = pd.DataFrame(
        {
            "Posting Date": ["2024-01-02", "2024-01-03"],
            "Description": ["ACH DEBIT ACME", "POS PURCHASE CAFE"],
            "Amount": [-100.0, -4.5],
        }
    )
    roles = detect_roles(frame)
    assert roles.date == "Posting Date"
    assert roles.amount == "Amount"
    assert roles.description == ["Description"]


def test_detect_roles_combines_split_debit_and_credit_columns():
    frame = pd.DataFrame(
        {
            "Date": ["2024-01-02", "2024-01-03"],
            "Narrative": ["Payment out", "Receipt in"],
            "Debit": [100.0, None],
            "Credit": [None, 250.0],
        }
    )
    table = normalize_table(frame, "bank")
    assert table.roles.debit == "Debit"
    assert table.roles.credit == "Credit"
    assert table.amount.tolist() == [-100.0, 250.0]


def test_row_id_column_is_not_mistaken_for_the_amount():
    frame = pd.DataFrame(
        {
            "Id": [1, 2, 3],
            "Date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "Memo": ["a", "b", "c"],
            "Value": [10.25, -3.5, 7.75],
        }
    )
    assert detect_roles(frame).amount == "Value"


def test_reference_extraction_normalises_document_numbers():
    references = extract_references(["INV-2001", "payment for inv 000345"])
    assert "INV2001" in references
    assert "345" in references


def test_informative_tokens_drop_banking_boilerplate():
    tokens = informative_tokens("ach debit northwind traders")
    assert "northwind" in tokens and "traders" in tokens
    assert "ach" not in tokens and "debit" not in tokens


def test_informative_tokens_keep_something_when_all_words_are_noise():
    assert informative_tokens("ach debit transfer") != set()


def test_normalize_table_survives_a_table_with_no_usable_columns():
    table = normalize_table(pd.DataFrame({"note": ["hello", "world"]}), "odd")
    assert len(table) == 2
    assert table.amount.isna().all()


def test_numeric_amount_column_is_never_mistaken_for_a_date():
    """pandas reads bare numbers as epoch nanoseconds; amounts are not dates."""
    frame = pd.DataFrame({"Date": ["", ""], "Memo": ["a", "b"], "Amount": [-100.0, 250.0]})
    roles = detect_roles(frame)
    assert roles.date is None
    assert roles.amount == "Amount"


def test_yyyymmdd_integer_dates_are_understood():
    frame = pd.DataFrame(
        {"Booking": [20240102, 20240315], "Memo": ["a", "b"], "Amount": [-1.0, 2.0]}
    )
    table = normalize_table(frame, "bank")
    assert table.roles.date == "Booking"
    assert table.date.iloc[0] == pd.Timestamp("2024-01-02")
    assert table.date.iloc[1] == pd.Timestamp("2024-03-15")
