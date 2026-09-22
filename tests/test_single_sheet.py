"""Finding the two blocks of open items inside one sheet."""

import pandas as pd
import pytest

from bank_reconciliation.sample_data import generate_pack
from bank_reconciliation.single_sheet import detect_layout, read_grid, side_of


@pytest.fixture(scope="module")
def pack():
    return generate_pack()


def test_the_two_blocks_are_found(pack):
    sheet, truth = pack
    layout = detect_layout(sheet)
    assert layout.is_pack
    assert [section.label for section in layout.sections] == ["SAP", "Bank Statement"]
    assert layout.notes == []


def test_every_true_pair_sits_inside_the_detected_blocks(pack):
    sheet, truth = pack
    ledger, bank = detect_layout(sheet).sections
    for sap_row, bank_row in truth.items():
        assert sap_row in ledger.source_rows
        assert bank_row in bank.source_rows


def test_columns_are_taken_from_each_block_own_header(pack):
    sheet, _ = pack
    ledger, bank = detect_layout(sheet).sections
    assert list(ledger.frame.columns) == [
        "Posting Date", "Document No", "Text", "Amount", "Reference"
    ]
    assert list(bank.frame.columns) == ["Value Date", "Bank Reference", "Narrative", "Amount"]


def test_titles_balances_and_headers_are_not_treated_as_items(pack):
    sheet, _ = pack
    layout = detect_layout(sheet)
    claimed = {row for section in layout.sections for row in section.source_rows}
    assert 0 not in claimed      # "Bank Reconciliation Statement"
    assert 4 not in claimed      # "Balance as per Bank Statement  482310.77"
    assert 7 not in claimed      # the column header row
    assert len(sheet) - 1 not in claimed  # "Balance as per SAP"


def test_source_rows_map_to_spreadsheet_rows(pack):
    sheet, _ = pack
    ledger, _bank = detect_layout(sheet).sections
    first = ledger.source_rows[0]
    # frame row 0 is raw row `first`, which is spreadsheet row first + 1.
    assert ledger.first_excel_row == first + 1
    assert str(ledger.frame.iloc[0]["Document No"]) == str(sheet.iloc[first, 1])


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Unmatched items in SAP", "ledger"),
        ("Open items per general ledger", "ledger"),
        ("Unmatched items in Bank Statement", "bank"),
        ("Outstanding cheques per bank", "bank"),
        ("Unmatched items", None),
    ],
)
def test_side_detection(text, expected):
    assert side_of(text) == expected


def test_blocks_are_found_without_any_headings():
    """Some packs just have two lists separated by a blank row."""
    rows = [["Date", "Memo", "Amount"]]
    rows += [[f"2024-03-0{i+1}", f"Ledger item {i}", -100.0 - i] for i in range(5)]
    rows += [[None, None, None]]
    rows += [["Date", "Memo", "Amount"]]
    rows += [[f"2024-03-0{i+1}", f"Bank item {i}", -100.0 - i] for i in range(5)]
    layout = detect_layout(pd.DataFrame(rows))
    assert layout.is_pack
    assert [len(section) for section in layout.sections] == [5, 5]
    assert [section.label for section in layout.sections] == ["SAP", "Bank Statement"]
    assert any("assumed ledger first" in note for note in layout.notes)


def test_a_normal_two_column_table_is_not_a_pack():
    frame = pd.DataFrame(
        [["Date", "Memo", "Amount"]]
        + [[f"2024-03-0{i+1}", f"Item {i}", -10.0 * i] for i in range(6)]
    )
    layout = detect_layout(frame)
    assert not layout.is_pack
    assert layout.notes


def test_an_empty_sheet_is_reported_not_crashed():
    layout = detect_layout(pd.DataFrame())
    assert not layout.is_pack
    assert "empty" in layout.notes[0].lower()


def test_read_grid_keeps_row_numbers_aligned(tmp_path):
    """Row i of the grid must be spreadsheet row i + 1, blanks included."""
    import openpyxl

    target = tmp_path / "gaps.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet["A4"] = "Title"
    sheet["A7"] = "Item"
    sheet["B7"] = 123.45
    book.save(target)

    grid = read_grid(str(target))
    assert grid.iloc[3, 0] == "Title"     # spreadsheet row 4
    assert grid.iloc[6, 0] == "Item"      # spreadsheet row 7
    assert grid.iloc[6, 1] == 123.45


def test_read_grid_keeps_blank_lines_in_csv(tmp_path):
    target = tmp_path / "gaps.csv"
    target.write_text("a,1\n\n\nb,2\n")
    grid = read_grid(str(target))
    assert len(grid) == 4
    assert grid.iloc[3, 0] == "b"
