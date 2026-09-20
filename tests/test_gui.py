"""The desktop app.

The job logic is tested directly; the widgets are driven for real when a
Tk-capable interpreter and a display are available, and skipped otherwise.
"""

import os

import pytest

from bank_reconciliation.gui import (
    JobRequest,
    default_output_path,
    list_sheets,
    read_sheet,
    run_job,
)
from bank_reconciliation.matcher import ReconciliationConfig
from bank_reconciliation.sample_data import write_sample_workbook


@pytest.fixture
def workbook(tmp_path):
    return write_sample_workbook(str(tmp_path / "book.xlsx"), n_matched=25, seed=29)


def make_request(workbook, tmp_path, **overrides):
    defaults = dict(
        statement_path=workbook,
        statement_sheet="Bank_Statement",
        ledger_path=workbook,
        ledger_sheet="Internal_Ledger",
        output_path=str(tmp_path / "out.xlsx"),
        config=ReconciliationConfig(),
    )
    defaults.update(overrides)
    return JobRequest(**defaults)


def test_list_sheets_hides_previously_generated_output(tmp_path, workbook):
    import pandas as pd

    with pd.ExcelWriter(workbook, engine="openpyxl", mode="a") as writer:
        pd.DataFrame({"a": [1]}).to_excel(writer, sheet_name="Matches", index=False)
    assert "Matches" not in list_sheets(workbook)
    assert list_sheets(workbook) == ["Bank_Statement", "Internal_Ledger"]


def test_read_sheet_handles_csv(tmp_path):
    import pandas as pd

    target = tmp_path / "rows.csv"
    pd.DataFrame({"a": [1, 2]}).to_csv(target, index=False)
    assert len(read_sheet(str(target), target.name)) == 2


def test_default_output_path_sits_beside_the_input():
    assert default_output_path("/data/march.xlsx") == "/data/march_reconciled.xlsx"


def test_run_job_writes_a_coloured_workbook(workbook, tmp_path):
    result, output = run_job(make_request(workbook, tmp_path))
    assert os.path.exists(output)
    assert result.records
    assert "Auto-matched pairs" in result.summary


def test_run_job_refuses_to_overwrite_the_source(workbook, tmp_path):
    request = make_request(workbook, tmp_path, output_path=workbook)
    with pytest.raises(ValueError, match="overwrite"):
        run_job(request)


def test_run_job_rejects_comparing_a_sheet_with_itself(workbook, tmp_path):
    request = make_request(workbook, tmp_path, ledger_sheet="Bank_Statement")
    with pytest.raises(ValueError, match="two different sheets"):
        run_job(request)


def test_run_job_rejects_a_missing_file(tmp_path):
    request = make_request(str(tmp_path / "ghost.xlsx"), tmp_path)
    with pytest.raises(ValueError, match="statement file"):
        run_job(request)


def test_run_job_rejects_an_empty_sheet(tmp_path):
    import pandas as pd

    target = tmp_path / "empty.xlsx"
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        pd.DataFrame({"Date": [], "Memo": [], "Amount": []}).to_excel(
            writer, sheet_name="Bank_Statement", index=False
        )
        pd.DataFrame({"Date": ["2024-01-02"], "Memo": ["x"], "Amount": [-1.0]}).to_excel(
            writer, sheet_name="Internal_Ledger", index=False
        )
    request = make_request(str(target), tmp_path)
    with pytest.raises(ValueError, match="no rows"):
        run_job(request)


# --------------------------------------------------------------------- widgets
def _tk_available() -> bool:
    try:
        import tkinter
    except ImportError:
        return False
    if not (os.environ.get("DISPLAY") or os.name == "nt"):
        return False
    try:
        root = tkinter.Tk()
    except Exception:  # noqa: BLE001 - no usable display
        return False
    root.destroy()
    return True


tk_only = pytest.mark.skipif(not _tk_available(), reason="needs tkinter and a display")


@tk_only
def test_window_builds_and_reconciles_end_to_end(workbook, tmp_path):
    import time

    from bank_reconciliation.gui import ReconcilerApp

    app = ReconcilerApp()
    try:
        app.statement_path.set(workbook)
        app.ledger_path.set(workbook)
        app.output_path.set(str(tmp_path / "gui_out.xlsx"))
        app._load_sheets(workbook, which="both")
        assert app.statement_sheet.get() == "Bank_Statement"
        assert app.ledger_sheet.get() == "Internal_Ledger"

        app.run_button.invoke()
        deadline = time.time() + 120
        while time.time() < deadline:
            app.root.update()
            if str(app.run_button["state"]) == "normal" and app.tree.get_children():
                break
            time.sleep(0.05)

        metrics = {
            app.tree.item(item)["values"][0]: app.tree.item(item)["values"][1]
            for item in app.tree.get_children()
        }
        assert "Auto-matched pairs" in metrics
        assert os.path.exists(tmp_path / "gui_out.xlsx")
        assert "Done." in app.status.get()
        assert str(app.open_button["state"]) == "normal"
    finally:
        app.root.destroy()


@tk_only
def test_bad_numeric_input_is_caught_before_any_work(workbook, tmp_path):
    from bank_reconciliation.gui import ReconcilerApp

    app = ReconcilerApp()
    try:
        app.statement_path.set(workbook)
        app.amount_tolerance.set("not a number")
        with pytest.raises(ValueError, match="must be a number"):
            app._collect_request()
    finally:
        app.root.destroy()
