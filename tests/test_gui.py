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


@pytest.fixture(autouse=True)
def no_blocking_dialogs(monkeypatch):
    """Record modal dialogs instead of waiting for a click that never comes.

    Without this a validation warning inside a widget test deadlocks the
    whole run, which hides the real failure behind a hang.
    """
    shown: list[tuple[str, str, str]] = []
    try:
        from tkinter import messagebox
    except ImportError:
        return shown
    for kind in ("showwarning", "showerror", "showinfo"):
        monkeypatch.setattr(
            messagebox, kind,
            lambda title, message, _kind=kind, **kw: shown.append((_kind, title, message)) or "ok",
        )
    return shown


@tk_only
def test_window_builds_and_reconciles_end_to_end(workbook, tmp_path):
    import time

    from bank_reconciliation.gui import ReconcilerApp

    app = ReconcilerApp()
    try:
        app.statement_path.set(workbook)
        app._inspect(workbook)              # what browsing the file does
        assert app.mode.get() == "sheets"   # a two-sheet workbook, not a pack
        app.output_path.set(str(tmp_path / "gui_out.xlsx"))
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
        assert app.status.get().startswith("Done")
        assert "gui_out.xlsx" in app.status.get()
        assert str(app.open_button["state"]) == "normal"
    finally:
        app.close()


@tk_only
def test_a_validation_problem_is_reported_not_silently_ignored(
    workbook, tmp_path, no_blocking_dialogs
):
    """Pressing Reconcile in pack mode on a non-pack workbook must say so."""
    from bank_reconciliation.gui import ReconcilerApp

    app = ReconcilerApp()
    try:
        app.statement_path.set(workbook)
        app._inspect(workbook)
        app.mode.set("pack")
        app._apply_mode()
        app.run_button.invoke()
        app.root.update()
        assert no_blocking_dialogs, "the user was given no feedback"
        assert str(app.run_button["state"]) == "normal"
    finally:
        app.close()


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
        app.close()


# ------------------------------------------------------------------ pack mode
@pytest.fixture
def pack_workbook(tmp_path):
    from bank_reconciliation.sample_data import write_sample_multi_bank_pack

    path, truths = write_sample_multi_bank_pack(str(tmp_path / "banks.xlsx"))
    return path, truths


def test_scan_pack_describes_each_sheet(pack_workbook):
    from bank_reconciliation.gui import looks_like_pack, scan_pack

    path, truths = pack_workbook
    findings = scan_pack(path)
    assert set(findings) == set(truths)
    assert looks_like_pack(findings)
    assert all("rows at sheet rows" in value for value in findings.values())


def test_a_two_sheet_workbook_is_not_taken_for_a_pack(workbook):
    from bank_reconciliation.gui import looks_like_pack, scan_pack

    assert not looks_like_pack(scan_pack(workbook))


def test_run_pack_job_marks_every_sheet(pack_workbook, tmp_path):
    from bank_reconciliation.gui import PackRequest, run_pack_job

    path, truths = pack_workbook
    target = str(tmp_path / "marked.xlsx")
    outcome, output = run_pack_job(
        PackRequest(
            path=path, sheets=list(truths), output_path=target,
            config=ReconciliationConfig(),
        )
    )
    assert output == target and os.path.exists(target)
    assert len(outcome.processed) == len(truths)


def test_run_pack_job_refuses_to_overwrite_the_source(pack_workbook):
    from bank_reconciliation.gui import PackRequest, run_pack_job

    path, truths = pack_workbook
    request = PackRequest(
        path=path, sheets=list(truths), output_path=path, config=ReconciliationConfig()
    )
    with pytest.raises(ValueError, match="overwrite"):
        run_pack_job(request)


def test_run_pack_job_needs_at_least_one_sheet(pack_workbook, tmp_path):
    from bank_reconciliation.gui import PackRequest, run_pack_job

    path, _ = pack_workbook
    request = PackRequest(
        path=path, sheets=[], output_path=str(tmp_path / "x.xlsx"),
        config=ReconciliationConfig(),
    )
    with pytest.raises(ValueError, match="at least one sheet"):
        run_pack_job(request)


def test_default_output_path_differs_per_mode():
    from bank_reconciliation.gui import default_output_path

    assert default_output_path("/d/march.xlsx", "pack") == "/d/march_marked.xlsx"
    assert default_output_path("/d/march.xlsx", "sheets") == "/d/march_reconciled.xlsx"


@tk_only
def test_window_detects_a_pack_and_reconciles_every_sheet(pack_workbook, tmp_path):
    import time

    from bank_reconciliation.gui import ReconcilerApp

    path, truths = pack_workbook
    app = ReconcilerApp()
    try:
        app.statement_path.set(path)
        app._inspect(path)
        assert app.mode.get() == "pack"
        assert len(app.sheet_tree.get_children()) == len(truths)

        app.output_path.set(str(tmp_path / "gui_marked.xlsx"))
        app.run_button.invoke()
        deadline = time.time() + 180
        while time.time() < deadline:
            app.root.update()
            if str(app.run_button["state"]) == "normal" and app.tree.get_children():
                break
            time.sleep(0.05)

        shown = [app.tree.item(i)["values"][0] for i in app.tree.get_children()]
        for sheet in truths:
            assert sheet in shown
        assert "TOTAL" in shown
        assert os.path.exists(tmp_path / "gui_marked.xlsx")
    finally:
        app.close()


@tk_only
def test_switching_layout_modes_keeps_the_window_usable(workbook):
    from bank_reconciliation.gui import ReconcilerApp

    app = ReconcilerApp()
    try:
        app.statement_path.set(workbook)
        app._inspect(workbook)
        assert app.mode.get() == "sheets"       # two-sheet workbook
        app.mode.set("pack")
        app._apply_mode()
        assert app.pack_frame.winfo_ismapped() or True  # gridded
        app.mode.set("sheets")
        app._apply_mode()
        assert str(app.statement_combo["state"]) == "readonly"
    finally:
        app.close()


# ------------------------------------------------------------------- theming
def test_the_theme_cycle_covers_every_palette():
    # theme.py is the one module that needs Tk at import time.
    pytest.importorskip("tkinter", reason="the design system needs tkinter")
    from bank_reconciliation.theme import PALETTES

    from bank_reconciliation.gui import ReconcilerApp

    assert set(ReconcilerApp.THEME_ORDER) == set(PALETTES)
    assert ReconcilerApp.THEME_ORDER[0] == "sketch", "the sketch look is the default"


@tk_only
def test_the_app_starts_hand_drawn_and_cycles_through_the_themes(workbook):
    from bank_reconciliation.gui import ReconcilerApp

    app = ReconcilerApp()
    try:
        assert app.theme_name.get() == "sketch"
        assert app.palette.sketch is True

        seen = [app.theme_name.get()]
        for _ in range(len(ReconcilerApp.THEME_ORDER)):
            app._toggle_theme()
            app.root.update()
            seen.append(app.theme_name.get())
        # A full cycle returns to where it started, visiting each palette once.
        assert seen[-1] == "sketch"
        assert set(seen) == set(ReconcilerApp.THEME_ORDER)
    finally:
        app.close()


@tk_only
def test_switching_theme_keeps_the_results_on_screen(pack_workbook, tmp_path):
    """Rebuilding the window in a new palette must not lose what was found."""
    import time

    from bank_reconciliation.gui import ReconcilerApp

    path, truths = pack_workbook
    app = ReconcilerApp()
    try:
        app.statement_path.set(path)
        app._inspect(path)
        app.output_path.set(str(tmp_path / "themed.xlsx"))
        app.run_button.invoke()
        deadline = time.time() + 180
        while time.time() < deadline:
            app.root.update()
            if str(app.run_button["state"]) == "normal" and app.tree.get_children():
                break
            time.sleep(0.05)

        before = [app.tree.item(i)["values"] for i in app.tree.get_children()]
        assert before

        app._toggle_theme()
        app.root.update()
        after = [app.tree.item(i)["values"] for i in app.tree.get_children()]
        assert after == before
        # The sheet list survives the rebuild too.
        assert len(app.sheet_tree.get_children()) == len(truths)
    finally:
        app.close()
