"""The command line interface."""

import openpyxl
import pandas as pd
import pytest

from bank_reconciliation.cli import main
from bank_reconciliation.sample_data import write_sample_workbook


@pytest.fixture
def workbook(tmp_path):
    return write_sample_workbook(str(tmp_path / "statement.xlsx"), n_matched=30, seed=17)


def test_default_run_writes_a_coloured_copy(workbook, tmp_path, capsys):
    assert main([workbook]) == 0
    output = tmp_path / "statement_reconciled.xlsx"
    assert output.exists()
    book = openpyxl.load_workbook(output)
    assert "Legend" in book.sheetnames
    assert "Auto-matched pairs" in capsys.readouterr().out


def test_source_file_is_left_untouched(workbook):
    before = openpyxl.load_workbook(workbook).sheetnames
    main([workbook])
    assert openpyxl.load_workbook(workbook).sheetnames == before


def test_tables_mode_writes_the_plain_report(workbook, tmp_path):
    target = tmp_path / "tables.xlsx"
    assert main([workbook, "--tables", "-o", str(target)]) == 0
    assert set(openpyxl.load_workbook(target).sheetnames) >= {"Summary", "Matches"}


def test_in_place_appends_to_the_source_workbook(workbook):
    assert main([workbook, "--in-place"]) == 0
    names = openpyxl.load_workbook(workbook).sheetnames
    assert "Bank_Statement" in names and "Summary" in names


def test_refuses_to_overwrite_the_input(workbook):
    assert main([workbook, "-o", workbook]) == 2


def test_missing_file_is_reported(tmp_path):
    assert main([str(tmp_path / "nope.xlsx")]) == 2


def test_contradictory_thresholds_are_rejected(workbook):
    assert main([workbook, "--match-threshold", "0.2", "--review-threshold", "0.9"]) == 2


def test_two_separate_files(tmp_path):
    from bank_reconciliation.sample_data import generate_sample

    sample = generate_sample(n_matched=25, seed=19)
    bank = tmp_path / "bank.csv"
    ledger = tmp_path / "ledger.csv"
    sample.bank.to_csv(bank, index=False)
    sample.ledger.to_csv(ledger, index=False)
    target = tmp_path / "out.xlsx"
    assert main([str(bank), "--ledger", str(ledger), "-o", str(target)]) == 0
    assert target.exists()


def test_csv_dir_output(workbook, tmp_path):
    csv_dir = tmp_path / "csvs"
    assert main([workbook, "--csv-dir", str(csv_dir)]) == 0
    assert len(list(csv_dir.glob("*.csv"))) == 4


def test_explicit_sheets(workbook, tmp_path):
    target = tmp_path / "explicit.xlsx"
    assert main([workbook, "--sheets", "Internal_Ledger", "Bank_Statement",
                 "-o", str(target)]) == 0
    assert target.exists()


def test_unknown_sheet_is_reported(workbook, tmp_path):
    with pytest.raises(SystemExit):
        main([workbook, "--sheets", "Nope", "Bank_Statement"])


def test_model_can_be_saved_and_reused(workbook, tmp_path):
    model = tmp_path / "scorer.joblib"
    assert main([workbook, "--save-model", str(model), "-o", str(tmp_path / "a.xlsx")]) == 0
    if model.exists():  # only written when a model could actually be trained
        assert main([workbook, "--load-model", str(model),
                     "-o", str(tmp_path / "b.xlsx")]) == 0


def test_single_sheet_workbook_is_reported(tmp_path):
    target = tmp_path / "one.xlsx"
    pd.DataFrame({"Date": ["2024-01-02"], "Memo": ["x"], "Amount": [-1.0]}).to_excel(
        target, sheet_name="Only", index=False
    )
    with pytest.raises(SystemExit):
        main([str(target)])


# ------------------------------------------------------------------ pack mode
@pytest.fixture
def pack_workbook(tmp_path):
    from bank_reconciliation.sample_data import write_sample_multi_bank_pack

    path, truths = write_sample_multi_bank_pack(str(tmp_path / "banks.xlsx"))
    return path, truths


def test_pack_layout_is_detected_automatically(pack_workbook, tmp_path, capsys):
    path, truths = pack_workbook
    assert main([path]) == 0
    output = tmp_path / "banks_marked.xlsx"
    assert output.exists()
    printed = capsys.readouterr().out
    for sheet in truths:
        assert sheet in printed
    assert "Total:" in printed


def test_pack_mode_can_be_forced(pack_workbook, tmp_path):
    path, _ = pack_workbook
    target = tmp_path / "forced.xlsx"
    assert main([path, "--mode", "pack", "-o", str(target)]) == 0
    assert target.exists()


def test_pack_output_has_a_summary_sheet_first(pack_workbook, tmp_path):
    path, _ = pack_workbook
    target = tmp_path / "out.xlsx"
    main([path, "-o", str(target)])
    assert openpyxl.load_workbook(target).sheetnames[0] == "Reconciliation Summary"


def test_pack_mode_refuses_to_overwrite_the_input(pack_workbook):
    path, _ = pack_workbook
    assert main([path, "-o", path]) == 2


def test_pack_mode_on_a_workbook_with_no_packs_fails_cleanly(workbook, tmp_path):
    assert main([workbook, "--mode", "pack", "-o", str(tmp_path / "x.xlsx")]) == 1


def test_sheets_mode_can_be_forced_on_a_pack(pack_workbook, tmp_path):
    """--mode sheets treats the sheets as two plain tables instead."""
    path, truths = pack_workbook
    names = list(truths)
    target = tmp_path / "as_sheets.xlsx"
    assert main([path, "--mode", "sheets", "--sheets", names[0], names[1],
                 "-o", str(target)]) == 0
    assert target.exists()


def test_selected_sheets_only(pack_workbook, tmp_path):
    path, truths = pack_workbook
    chosen = list(truths)[0]
    target = tmp_path / "one.xlsx"
    assert main([path, "--mode", "pack", "--sheets", chosen, "-o", str(target)]) == 0
    book = openpyxl.load_workbook(target)
    summary = book["Reconciliation Summary"]
    text = " ".join(
        str(summary.cell(row=r, column=c).value)
        for r in range(1, summary.max_row + 1) for c in range(1, 4)
    )
    assert chosen in text
