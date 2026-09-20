"""A desktop front end for the reconciler.

The user picks a workbook, chooses which sheet is the bank statement and
which is the ledger, and gets back a colour-coded copy of their own data.
Everything heavy runs on a worker thread so the window never freezes; the
worker talks back through a queue that the UI drains on a timer, because
Tk widgets may only be touched from the main thread.
"""

from __future__ import annotations

import os
import queue
import threading
import traceback
from dataclasses import dataclass

import pandas as pd

from .highlight import write_highlighted_workbook
from .matcher import ReconciliationConfig, ReconciliationResult, reconcile
from .pack import PackOutcome, mark_workbook, reconcile_pack, sheet_names
from .single_sheet import detect_layout, read_grid

SPREADSHEET_TYPES = [
    ("Excel workbooks", "*.xlsx *.xlsm *.xls"),
    ("CSV files", "*.csv"),
    ("All files", "*.*"),
]

SWATCHES = [
    ("#C6EFCE", "#006100", "Matched automatically"),
    ("#BDD7EE", "#1F4E79", "Grouped match (one bank line, several ledger lines)"),
    ("#FFEB9C", "#9C6500", "Needs review"),
    ("#FFC7CE", "#9C0006", "Unmatched"),
]

GENERATED_SHEETS = {"legend", "matches", "summary"}


def list_sheets(path: str) -> list[str]:
    """Sheet names in a workbook; a single pseudo-sheet for a CSV."""
    if os.path.splitext(path)[1].lower() in {".csv", ".txt", ".tsv"}:
        return [os.path.basename(path)]
    names = pd.ExcelFile(path).sheet_names
    usable = [
        name for name in names
        if name.lower() not in GENERATED_SHEETS
        and not name.lower().startswith(("unmatched_", "ml_reconciliation"))
    ]
    return usable or names


def read_sheet(path: str, sheet: str) -> pd.DataFrame:
    extension = os.path.splitext(path)[1].lower()
    if extension in {".csv", ".txt", ".tsv"}:
        return pd.read_csv(path, sep="\t" if extension == ".tsv" else ",")
    return pd.read_excel(path, sheet_name=sheet)


def default_output_path(statement_path: str, mode: str = "sheets") -> str:
    stem, _ = os.path.splitext(statement_path)
    return f"{stem}_marked.xlsx" if mode == "pack" else f"{stem}_reconciled.xlsx"


def scan_pack(path: str) -> dict[str, str]:
    """Describe what was found in each sheet of a workbook.

    Used to pick the right mode automatically and to tell the user, per
    sheet, whether two blocks of open items could be identified.
    """
    findings: dict[str, str] = {}
    for sheet in sheet_names(path):
        try:
            layout = detect_layout(read_grid(path, sheet))
        except Exception as error:  # noqa: BLE001 - reported per sheet
            findings[sheet] = f"could not read: {error}"
            continue
        if layout.is_pack:
            findings[sheet] = " / ".join(section.describe() for section in layout.sections)
        else:
            findings[sheet] = layout.notes[-1] if layout.notes else "no two blocks found"
    return findings


def looks_like_pack(findings: dict[str, str]) -> bool:
    """True when at least one sheet holds both sides stacked together."""
    return any(" rows at sheet rows " in value for value in findings.values())


@dataclass
class PackRequest:
    """A run over a workbook whose every sheet is its own reconciliation."""

    path: str
    sheets: list[str]
    output_path: str
    config: ReconciliationConfig

    def validate(self) -> None:
        if not self.path or not os.path.exists(self.path):
            raise ValueError("Choose a workbook first.")
        if not self.sheets:
            raise ValueError("Select at least one sheet to reconcile.")
        if os.path.abspath(self.output_path) == os.path.abspath(self.path):
            raise ValueError("The output file would overwrite your source data. Pick another name.")
        self.config.validate()


def run_pack_job(request: PackRequest) -> tuple[PackOutcome, str]:
    """Reconcile every selected sheet against itself and mark a copy."""
    request.validate()
    outcome = reconcile_pack(request.path, config=request.config, sheets=request.sheets)
    if not outcome.processed:
        raise ValueError(
            "None of the selected sheets held two blocks of open items. "
            "Check that each sheet lists the ledger items and the bank items separately."
        )
    mark_workbook(outcome, request.output_path)
    return outcome, request.output_path


@dataclass
class JobRequest:
    """Everything the worker thread needs to do one reconciliation."""

    statement_path: str
    statement_sheet: str
    ledger_path: str
    ledger_sheet: str
    output_path: str
    config: ReconciliationConfig

    def validate(self) -> None:
        if not self.statement_path or not os.path.exists(self.statement_path):
            raise ValueError("Choose a statement file first.")
        if not os.path.exists(self.ledger_path):
            raise ValueError("Choose a ledger file first.")
        same_file = os.path.abspath(self.statement_path) == os.path.abspath(self.ledger_path)
        if same_file and self.statement_sheet == self.ledger_sheet:
            raise ValueError("Pick two different sheets to compare.")
        if os.path.abspath(self.output_path) in {
            os.path.abspath(self.statement_path), os.path.abspath(self.ledger_path)
        }:
            raise ValueError("The output file would overwrite your source data. Pick another name.")
        self.config.validate()


def run_job(request: JobRequest) -> tuple[ReconciliationResult, str]:
    """Do the work. Pure logic, so it can be tested without a display."""
    request.validate()
    statement = read_sheet(request.statement_path, request.statement_sheet)
    ledger = read_sheet(request.ledger_path, request.ledger_sheet)
    if statement.empty or ledger.empty:
        raise ValueError("One of the selected sheets has no rows in it.")

    left_name, right_name = request.statement_sheet, request.ledger_sheet
    if left_name == right_name:
        left_name, right_name = f"{left_name}_A", f"{right_name}_B"

    result = reconcile(statement, ledger, left_name, right_name, config=request.config)
    write_highlighted_workbook(result, request.output_path)
    return result, request.output_path


def _open_in_file_manager(path: str) -> None:
    """Reveal a finished file using whatever the platform provides."""
    import subprocess
    import sys

    target = path if os.path.exists(path) else os.path.dirname(path)
    try:
        if sys.platform.startswith("darwin"):
            subprocess.Popen(["open", "-R", target])
        elif os.name == "nt":
            os.startfile(os.path.dirname(target))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(target)])
    except OSError:
        pass


class ReconcilerApp:
    """The Tk window."""

    def __init__(self, master=None) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = master or tk.Tk()
        self.root.title("Bank Reconciliation")
        self.root.minsize(760, 620)

        self.statement_path = tk.StringVar()
        self.ledger_path = tk.StringVar()
        self.statement_sheet = tk.StringVar()
        self.ledger_sheet = tk.StringVar()
        self.output_path = tk.StringVar()
        self.separate_ledger_file = tk.BooleanVar(value=False)
        self.mode = tk.StringVar(value="pack")
        self._findings: dict[str, str] = {}

        self.amount_tolerance = tk.StringVar(value="0.01")
        self.date_window = tk.StringVar(value="5")
        self.match_threshold = tk.StringVar(value="0.60")
        self.review_threshold = tk.StringVar(value="0.35")
        self.sign_convention = tk.StringVar(value="auto")
        self.group_matching = tk.BooleanVar(value=True)

        self.status = tk.StringVar(value="Choose an Excel file to begin.")
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._last_output: str | None = None

        self._build()
        self.root.after(100, self._drain_queue)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        tk, ttk = self.tk, self.ttk
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        padding = {"padx": 8, "pady": 4}

        # --- source files -------------------------------------------------
        source = ttk.LabelFrame(root, text="1. Data")
        source.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        source.columnconfigure(1, weight=1)

        ttk.Label(source, text="Workbook:").grid(row=0, column=0, sticky="w", **padding)
        ttk.Entry(source, textvariable=self.statement_path).grid(
            row=0, column=1, sticky="ew", **padding
        )
        ttk.Button(source, text="Browse...", command=self._browse_statement).grid(
            row=0, column=2, **padding
        )

        mode_frame = ttk.Frame(source)
        mode_frame.grid(row=6, column=0, columnspan=3, sticky="w", padx=8, pady=(6, 2))
        ttk.Label(mode_frame, text="Layout:").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            mode_frame,
            text="Each sheet is a full reconciliation (ledger items above, bank items below)",
            variable=self.mode,
            value="pack",
            command=self._apply_mode,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Radiobutton(
            mode_frame,
            text="One sheet is the statement, another is the ledger",
            variable=self.mode,
            value="sheets",
            command=self._apply_mode,
        ).grid(row=1, column=1, sticky="w", padx=(8, 0))

        # --- pack mode: what was found in each sheet ----------------------
        self.pack_frame = ttk.Frame(source)
        self.pack_frame.columnconfigure(0, weight=1)
        ttk.Label(
            self.pack_frame,
            text="Sheets to reconcile (each is matched against itself):",
        ).grid(row=0, column=0, sticky="w", pady=(4, 2))
        self.sheet_tree = ttk.Treeview(
            self.pack_frame, columns=("sheet", "found"), show="headings",
            height=6, selectmode="extended",
        )
        self.sheet_tree.heading("sheet", text="Sheet")
        self.sheet_tree.heading("found", text="What was found")
        self.sheet_tree.column("sheet", width=170, anchor="w")
        self.sheet_tree.column("found", width=470, anchor="w")
        self.sheet_tree.grid(row=1, column=0, sticky="ew")
        pack_scroll = ttk.Scrollbar(
            self.pack_frame, orient="vertical", command=self.sheet_tree.yview
        )
        pack_scroll.grid(row=1, column=1, sticky="ns")
        self.sheet_tree.configure(yscrollcommand=pack_scroll.set)
        ttk.Label(
            self.pack_frame,
            text="Nothing selected means every usable sheet.",
        ).grid(row=2, column=0, sticky="w", pady=(2, 0))

        # --- two-sheet mode ------------------------------------------------
        self.sheets_frame = ttk.Frame(source)
        self.sheets_frame.columnconfigure(1, weight=1)

        self.statement_label = ttk.Label(source, text="Bank statement sheet:")
        self.statement_label.grid(row=1, column=0, sticky="w", **padding)
        self.statement_combo = ttk.Combobox(
            source, textvariable=self.statement_sheet, state="readonly"
        )
        self.statement_combo.grid(row=1, column=1, sticky="ew", **padding)

        self.separate_check = ttk.Checkbutton(
            source,
            text="Ledger is in a separate file",
            variable=self.separate_ledger_file,
            command=self._toggle_separate_ledger,
        )
        self.separate_check.grid(row=2, column=1, sticky="w", **padding)

        self.ledger_label = ttk.Label(source, text="Ledger file:")
        self.ledger_entry = ttk.Entry(source, textvariable=self.ledger_path)
        self.ledger_button = ttk.Button(source, text="Browse...", command=self._browse_ledger)

        self.ledger_sheet_label = ttk.Label(source, text="Ledger sheet:")
        self.ledger_sheet_label.grid(row=4, column=0, sticky="w", **padding)
        self.ledger_combo = ttk.Combobox(source, textvariable=self.ledger_sheet, state="readonly")
        self.ledger_combo.grid(row=4, column=1, sticky="ew", **padding)

        self.output_label = ttk.Label(source, text="Save marked copy to:")
        self.output_label.grid(row=5, column=0, sticky="w", **padding)
        ttk.Entry(source, textvariable=self.output_path).grid(row=5, column=1, sticky="ew", **padding)
        ttk.Button(source, text="Change...", command=self._browse_output).grid(
            row=5, column=2, **padding
        )

        # --- settings -----------------------------------------------------
        settings = ttk.LabelFrame(root, text="2. Matching rules")
        settings.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        for column in (1, 3):
            settings.columnconfigure(column, weight=1)

        ttk.Label(settings, text="Amount tolerance:").grid(row=0, column=0, sticky="w", **padding)
        ttk.Entry(settings, textvariable=self.amount_tolerance, width=10).grid(
            row=0, column=1, sticky="w", **padding
        )
        ttk.Label(settings, text="Date window (days):").grid(row=0, column=2, sticky="w", **padding)
        ttk.Entry(settings, textvariable=self.date_window, width=10).grid(
            row=0, column=3, sticky="w", **padding
        )

        ttk.Label(settings, text="Auto-match above:").grid(row=1, column=0, sticky="w", **padding)
        ttk.Entry(settings, textvariable=self.match_threshold, width=10).grid(
            row=1, column=1, sticky="w", **padding
        )
        ttk.Label(settings, text="Review above:").grid(row=1, column=2, sticky="w", **padding)
        ttk.Entry(settings, textvariable=self.review_threshold, width=10).grid(
            row=1, column=3, sticky="w", **padding
        )

        ttk.Label(settings, text="Ledger signs:").grid(row=2, column=0, sticky="w", **padding)
        ttk.Combobox(
            settings,
            textvariable=self.sign_convention,
            state="readonly",
            width=8,
            values=("auto", "same", "flip"),
        ).grid(row=2, column=1, sticky="w", **padding)
        ttk.Checkbutton(
            settings,
            text="Match one bank line against several ledger lines",
            variable=self.group_matching,
        ).grid(row=2, column=2, columnspan=2, sticky="w", **padding)

        # --- action -------------------------------------------------------
        action = ttk.Frame(root)
        action.grid(row=2, column=0, sticky="ew", padx=10, pady=4)
        action.columnconfigure(1, weight=1)

        self.run_button = ttk.Button(action, text="Reconcile", command=self._start)
        self.run_button.grid(row=0, column=0, padx=(0, 8))
        self.progress = ttk.Progressbar(action, mode="indeterminate")
        self.progress.grid(row=0, column=1, sticky="ew")
        self.open_button = ttk.Button(
            action, text="Open output folder", command=self._open_output, state="disabled"
        )
        self.open_button.grid(row=0, column=2, padx=(8, 0))

        # --- results ------------------------------------------------------
        results = ttk.LabelFrame(root, text="3. Result")
        results.grid(row=3, column=0, sticky="nsew", padx=10, pady=4)
        results.columnconfigure(0, weight=1)
        results.rowconfigure(1, weight=1)

        legend = ttk.Frame(results)
        legend.grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        for index, (background, foreground, caption) in enumerate(SWATCHES):
            self.tk.Label(
                legend, text="     ", background=background, relief="solid", borderwidth=1
            ).grid(row=index, column=0, padx=(0, 6), pady=1)
            self.tk.Label(legend, text=caption, foreground=foreground).grid(
                row=index, column=1, sticky="w"
            )

        self.tree = ttk.Treeview(results, columns=("metric", "value"), show="headings", height=9)
        self.tree.heading("metric", text="Sheet / Metric")
        self.tree.heading("value", text="Result")
        self.tree.column("metric", width=290, anchor="w")
        self.tree.column("value", width=380, anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew", padx=8, pady=(2, 8))
        scrollbar = ttk.Scrollbar(results, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns", pady=(2, 8))
        self.tree.configure(yscrollcommand=scrollbar.set)

        ttk.Label(root, textvariable=self.status, anchor="w").grid(
            row=4, column=0, sticky="ew", padx=12, pady=(0, 10)
        )
        self._two_sheet_widgets = [
            (self.statement_label, dict(row=1, column=0, sticky="w", **padding)),
            (self.statement_combo, dict(row=1, column=1, sticky="ew", **padding)),
            (self.separate_check, dict(row=2, column=1, sticky="w", **padding)),
            (self.ledger_sheet_label, dict(row=4, column=0, sticky="w", **padding)),
            (self.ledger_combo, dict(row=4, column=1, sticky="ew", **padding)),
        ]
        self._apply_mode()

    def _apply_mode(self) -> None:
        """Show the controls that belong to the selected layout."""
        pack = self.mode.get() == "pack"
        if pack:
            for widget, _ in self._two_sheet_widgets:
                widget.grid_remove()
            self.ledger_label.grid_remove()
            self.ledger_entry.grid_remove()
            self.ledger_button.grid_remove()
            self.pack_frame.grid(row=7, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
            self.output_label.configure(text="Save marked copy to:")
        else:
            self.pack_frame.grid_remove()
            for widget, options in self._two_sheet_widgets:
                widget.grid(**options)
            self._toggle_separate_ledger()
            self.output_label.configure(text="Save coloured copy to:")
        path = self.statement_path.get().strip()
        if path:
            self.output_path.set(default_output_path(path, self.mode.get()))

    def _toggle_separate_ledger(self) -> None:
        padding = {"padx": 8, "pady": 4}
        if self.mode.get() == "pack":
            return
        if self.separate_ledger_file.get():
            self.ledger_label.grid(row=3, column=0, sticky="w", **padding)
            self.ledger_entry.grid(row=3, column=1, sticky="ew", **padding)
            self.ledger_button.grid(row=3, column=2, **padding)
        else:
            self.ledger_label.grid_remove()
            self.ledger_entry.grid_remove()
            self.ledger_button.grid_remove()
            self.ledger_path.set(self.statement_path.get())
            self._load_sheets(self.statement_path.get(), which="both")

    # ------------------------------------------------------------- actions
    def _browse_statement(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(title="Choose the workbook", filetypes=SPREADSHEET_TYPES)
        if not path:
            return
        self.statement_path.set(path)
        self._inspect(path)

    def _browse_ledger(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(title="Choose the ledger", filetypes=SPREADSHEET_TYPES)
        if not path:
            return
        self.ledger_path.set(path)
        self._load_sheets(path, which="ledger")

    def _browse_output(self) -> None:
        from tkinter import filedialog

        path = filedialog.asksaveasfilename(
            title="Save coloured workbook as",
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
        )
        if path:
            self.output_path.set(path)

    def _inspect(self, path: str) -> None:
        """Work out how this workbook is laid out and set the UI up for it."""
        from tkinter import messagebox

        self.status.set("Reading the workbook...")
        self.root.update_idletasks()
        try:
            self._findings = scan_pack(path)
        except Exception as error:  # noqa: BLE001 - shown to the user
            messagebox.showerror("Could not read file", str(error))
            self.status.set("Could not read that file.")
            return

        self.mode.set("pack" if looks_like_pack(self._findings) else "sheets")
        self._populate_sheet_tree()
        self._apply_mode()

        if self.mode.get() == "pack":
            usable = sum(1 for v in self._findings.values() if " rows at sheet rows " in v)
            self.status.set(
                f"Found {usable} sheet(s) holding both sides. "
                "Select specific sheets, or just press Reconcile for all of them."
            )
        else:
            self.ledger_path.set(path)
            self._load_sheets(path, which="both")

    def _populate_sheet_tree(self) -> None:
        self.sheet_tree.delete(*self.sheet_tree.get_children())
        for sheet, finding in self._findings.items():
            self.sheet_tree.insert("", "end", iid=sheet, values=(sheet, finding))

    def _usable_sheets(self) -> list[str]:
        """The sheets a pack run should cover: the selection, or all usable."""
        selected = [str(item) for item in self.sheet_tree.selection()]
        if selected:
            return selected
        if not self._findings:
            # The path was typed in rather than browsed to, so nothing has
            # been scanned yet. Scan it now instead of reporting no sheets.
            path = self.statement_path.get().strip()
            if path and os.path.exists(path):
                try:
                    self._findings = scan_pack(path)
                    self._populate_sheet_tree()
                except Exception:  # noqa: BLE001 - validation reports the problem
                    return []
        return [
            sheet for sheet, finding in self._findings.items()
            if " rows at sheet rows " in finding
        ]

    def _load_sheets(self, path: str, which: str) -> None:
        from tkinter import messagebox

        if not path or not os.path.exists(path):
            return
        try:
            sheets = list_sheets(path)
        except Exception as error:  # noqa: BLE001 - shown to the user
            messagebox.showerror("Could not read file", str(error))
            return

        if which in {"statement", "both"}:
            self.statement_combo["values"] = sheets
            self.statement_sheet.set(sheets[0])
        if which in {"ledger", "both"}:
            self.ledger_combo["values"] = sheets
            self.ledger_sheet.set(sheets[1] if which == "both" and len(sheets) > 1 else sheets[0])

        if which == "both" and len(sheets) < 2:
            self.status.set(
                "This workbook has only one sheet - tick 'Ledger is in a separate file'."
            )
        else:
            self.status.set(f"Loaded {len(sheets)} sheet(s). Check the selections, then Reconcile.")

    def _collect_config(self) -> ReconciliationConfig:
        def number(variable, label: str, cast=float):
            raw = variable.get().strip()
            try:
                return cast(raw)
            except ValueError:
                raise ValueError(f"{label} must be a number (got {raw!r}).") from None

        return ReconciliationConfig(
            amount_tolerance=number(self.amount_tolerance, "Amount tolerance"),
            date_window_days=number(self.date_window, "Date window", int),
            match_threshold=number(self.match_threshold, "Auto-match threshold"),
            review_threshold=number(self.review_threshold, "Review threshold"),
            sign_convention=self.sign_convention.get(),
            group_matching=bool(self.group_matching.get()),
        )

    def _collect_request(self) -> JobRequest:
        config = self._collect_config()
        statement = self.statement_path.get().strip()
        ledger = self.ledger_path.get().strip() or statement
        return JobRequest(
            statement_path=statement,
            statement_sheet=self.statement_sheet.get(),
            ledger_path=ledger,
            ledger_sheet=self.ledger_sheet.get(),
            output_path=self.output_path.get().strip() or default_output_path(statement),
            config=config,
        )

    def _collect_pack_request(self) -> PackRequest:
        path = self.statement_path.get().strip()
        return PackRequest(
            path=path,
            sheets=self._usable_sheets(),
            output_path=(
                self.output_path.get().strip() or default_output_path(path, "pack")
            ),
            config=self._collect_config(),
        )

    def _start(self) -> None:
        from tkinter import messagebox

        if self._worker and self._worker.is_alive():
            return
        pack = self.mode.get() == "pack"
        try:
            request = self._collect_pack_request() if pack else self._collect_request()
            request.validate()
        except ValueError as error:
            messagebox.showwarning("Check the settings", str(error))
            return

        self.run_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.progress.start(12)
        self.status.set("Reconciling... this can take a moment on large statements.")
        self.tree.delete(*self.tree.get_children())

        def work() -> None:
            try:
                if pack:
                    outcome, output = run_pack_job(request)
                    self._queue.put(("pack_done", (outcome, output)))
                else:
                    result, output = run_job(request)
                    self._queue.put(("done", (result, output)))
            except Exception as error:  # noqa: BLE001 - reported in the UI
                self._queue.put(("error", (error, traceback.format_exc())))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "done":
                    self._on_success(*payload)
                elif kind == "pack_done":
                    self._on_pack_success(*payload)
                elif kind == "error":
                    self._on_error(*payload)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._drain_queue)

    def _on_success(self, result: ReconciliationResult, output: str) -> None:
        self.progress.stop()
        self.run_button.configure(state="normal")
        self.open_button.configure(state="normal")
        self._last_output = output
        for key, value in result.summary.items():
            self.tree.insert("", "end", values=(key, value))
        self.status.set(f"Done. Coloured workbook saved to {output}")

    def _on_pack_success(self, outcome: PackOutcome, output: str) -> None:
        self.progress.stop()
        self.run_button.configure(state="normal")
        self.open_button.configure(state="normal")
        self._last_output = output

        for sheet_outcome in outcome.sheets:
            if not sheet_outcome.ok:
                self.tree.insert("", "end", values=(sheet_outcome.sheet, f"skipped - {sheet_outcome.skipped}"))
                continue
            counts = sheet_outcome.counts
            self.tree.insert("", "end", values=(
                sheet_outcome.sheet,
                f"{counts['matched'] + counts['grouped']} matched, "
                f"{counts['review']} to review, "
                f"{counts['unmatched_ledger'] + counts['unmatched_bank']} still open",
            ))
        totals = outcome.totals
        self.tree.insert("", "end", values=("", ""))
        self.tree.insert("", "end", values=(
            "TOTAL",
            f"{totals['matched'] + totals['grouped']} matched, "
            f"{totals['review']} to review, "
            f"{totals['unmatched_ledger'] + totals['unmatched_bank']} still open",
        ))
        self.status.set(f"Done. Marked copy saved to {output}")

    def _on_error(self, error: Exception, detail: str) -> None:
        from tkinter import messagebox

        self.progress.stop()
        self.run_button.configure(state="normal")
        self.status.set("Reconciliation failed.")
        messagebox.showerror("Reconciliation failed", f"{error}\n\n{detail.splitlines()[-1]}")

    def _open_output(self) -> None:
        if self._last_output:
            _open_in_file_manager(self._last_output)

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print(
            "This GUI needs tkinter, which is missing from this Python install.\n"
            "  Debian/Ubuntu: sudo apt install python3-tk\n"
            "  Fedora:        sudo dnf install python3-tkinter\n"
            "  macOS/Windows: use the python.org installer, which bundles it.\n"
            "You can still reconcile from the terminal:\n"
            "  python -m bank_reconciliation statement.xlsx"
        )
        return 1
    ReconcilerApp().run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
