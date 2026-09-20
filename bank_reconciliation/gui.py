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

    def __init__(self, master=None, theme: str = "light") -> None:
        import tkinter as tk
        from tkinter import ttk

        from .theme import PALETTES, Typography

        self.tk = tk
        self.ttk = ttk
        self.root = master or tk.Tk()
        self.root.title("Bank Reconciliation")
        self.root.minsize(880, 700)
        self.root.geometry("980x860")

        self.theme_name = tk.StringVar(value=theme)
        self.palette = PALETTES[theme]
        self.type_scale = Typography.build(self.root)

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

        self.status = tk.StringVar(value="Choose a workbook to begin.")
        self.source_caption = tk.StringVar(value="No file selected yet.")
        self.layout_caption = tk.StringVar(value="")
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._last_output: str | None = None
        self._result_rows: list[tuple[str, str]] = []

        self._poll_id: str | None = None
        self._closing = False
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        # Also covers a caller that destroys the window directly: Tcl reports
        # "invalid command name" if a pending after() outlives the widget.
        self.root.bind("<Destroy>", self._on_destroy)
        self._poll_id = self.root.after(100, self._drain_queue)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        from .theme import (
            AutoHideScrollbar, Card, Chip, CollapsibleCard, RoundedButton,
            ScrollableFrame, SegmentedControl, ToggleSwitch, apply_theme,
            flatten_scrollbar,
        )

        tk, ttk = self.tk, self.ttk
        root, p, t = self.root, self.palette, self.type_scale
        style = apply_theme(root, p, t)
        flatten_scrollbar(style, p)

        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        # ---------------------------------------------------------- header
        header = ttk.Frame(root, style="Canvas.TFrame")
        header.grid(row=0, column=0, sticky="ew", padx=22, pady=(16, 10))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Bank Reconciliation", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Match your ledger against the bank, and mark up your own spreadsheet.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        self.theme_button = RoundedButton(
            header,
            text="Dark" if p.name == "light" else "Light",
            command=self._toggle_theme,
            palette=p, type_scale=t, kind="ghost", height=32,
            min_width=86, surface=p.canvas,
        )
        self.theme_button.grid(row=0, column=1, rowspan=2, sticky="e")

        # ----------------------------------------------------------- source
        self.scroller = ScrollableFrame(root, p)
        self.scroller.grid(row=1, column=0, sticky="nsew")
        sheet = self.scroller.body
        sheet.columnconfigure(0, weight=1)

        source_card = Card(sheet, p)
        source_card.grid(row=0, column=0, sticky="ew", padx=22, pady=(0, 10))
        source = source_card.body()
        source.columnconfigure(0, weight=1)

        ttk.Label(source, text="Source data", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            source,
            text="Pick the workbook. The layout is detected for you.",
            style="Caption.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(1, 10))

        file_row = ttk.Frame(source, style="Card.TFrame")
        file_row.grid(row=2, column=0, sticky="ew")
        file_row.columnconfigure(0, weight=1)
        ttk.Entry(file_row, textvariable=self.statement_path).grid(
            row=0, column=0, sticky="ew"
        )
        RoundedButton(
            file_row, text="Browse", command=self._browse_statement,
            palette=p, type_scale=t, kind="ghost", height=34, surface=p.card,
        ).grid(row=0, column=1, padx=(8, 0))

        ttk.Label(source, textvariable=self.source_caption, style="Caption.TLabel").grid(
            row=3, column=0, sticky="w", pady=(6, 0)
        )

        ttk.Separator(source, orient="horizontal", style="Sep.TSeparator").grid(
            row=4, column=0, sticky="ew", pady=14
        )

        ttk.Label(source, text="LAYOUT", style="FieldLabel.TLabel").grid(
            row=5, column=0, sticky="w", pady=(0, 5)
        )
        SegmentedControl(
            source,
            variable=self.mode,
            options=[("pack", "One sheet per bank"), ("sheets", "Statement + ledger")],
            palette=p, type_scale=t, command=self._apply_mode, surface=p.card,
        ).grid(row=6, column=0, sticky="w")
        ttk.Label(
            source, textvariable=self.layout_caption, style="Caption.TLabel"
        ).grid(row=7, column=0, sticky="w", pady=(6, 0))

        # pack mode: the per-sheet findings
        self.pack_frame = ttk.Frame(source, style="Card.TFrame")
        self.pack_frame.columnconfigure(0, weight=1)
        tree_wrap = tk.Frame(
            self.pack_frame, background=p.card_border, bd=0, highlightthickness=0
        )
        tree_wrap.grid(row=1, column=0, sticky="ew")
        tree_wrap.columnconfigure(0, weight=1)
        self.sheet_tree = ttk.Treeview(
            tree_wrap, columns=("sheet", "found"), show="headings",
            height=3, selectmode="extended",
        )
        self.sheet_tree.heading("sheet", text="SHEET", anchor="w")
        self.sheet_tree.heading("found", text="WHAT WAS FOUND", anchor="w")
        self.sheet_tree.column("sheet", width=190, anchor="w", stretch=False)
        self.sheet_tree.column("found", width=470, anchor="w")
        self.sheet_tree.grid(row=0, column=0, sticky="ew", padx=1, pady=1)
        sheet_scroll = AutoHideScrollbar(
            tree_wrap, orient="vertical", command=self.sheet_tree.yview,
            style="Flat.Vertical.TScrollbar",
        )
        sheet_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 1), pady=1)
        self.sheet_tree.configure(yscrollcommand=sheet_scroll.set)
        self.sheet_tree.tag_configure("odd", background=p.stripe)
        self.sheet_tree.tag_configure("skip", foreground=p.subtle)
        ttk.Label(
            self.pack_frame,
            text="Select specific sheets, or leave the selection empty for all of them.",
            style="Caption.TLabel",
        ).grid(row=2, column=0, sticky="w", pady=(5, 0))

        # two-sheet mode: the sheet pickers
        self.sheets_frame = ttk.Frame(source, style="Card.TFrame")
        self.sheets_frame.columnconfigure(0, weight=1)
        self.sheets_frame.columnconfigure(1, weight=1)

        statement_box = ttk.Frame(self.sheets_frame, style="Card.TFrame")
        statement_box.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        statement_box.columnconfigure(0, weight=1)
        ttk.Label(statement_box, text="Bank statement sheet", style="FieldLabel.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 3)
        )
        self.statement_combo = ttk.Combobox(
            statement_box, textvariable=self.statement_sheet, state="readonly"
        )
        self.statement_combo.grid(row=1, column=0, sticky="ew")

        ledger_box = ttk.Frame(self.sheets_frame, style="Card.TFrame")
        ledger_box.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ledger_box.columnconfigure(0, weight=1)
        ttk.Label(ledger_box, text="Ledger sheet", style="FieldLabel.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 3)
        )
        self.ledger_combo = ttk.Combobox(
            ledger_box, textvariable=self.ledger_sheet, state="readonly"
        )
        self.ledger_combo.grid(row=1, column=0, sticky="ew")

        self.separate_check = ToggleSwitch(
            self.sheets_frame, variable=self.separate_ledger_file,
            palette=p, type_scale=t, text="The ledger is in a separate file",
            command=self._toggle_separate_ledger, surface=p.card,
        )
        self.separate_check.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))

        self.ledger_label = ttk.Label(
            self.sheets_frame, text="Ledger file", style="FieldLabel.TLabel"
        )
        self.ledger_entry = ttk.Entry(self.sheets_frame, textvariable=self.ledger_path)
        self.ledger_button = RoundedButton(
            self.sheets_frame, text="Browse", command=self._browse_ledger,
            palette=p, type_scale=t, kind="ghost", height=34, surface=p.card,
        )

        # ------------------------------------------------------------ rules
        self.rules_card = CollapsibleCard(
            sheet, p, t,
            title="Matching rules",
            caption="The defaults suit most statements \u00b7 confidence runs from 0 to 1",
            expanded=False,
            on_toggle=self._on_rules_toggle,
        )
        self.rules_card.grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 10))
        rules = self.rules_card.content
        for column in range(3):
            rules.columnconfigure(column, weight=1, uniform="rules")

        def field(parent, row, column, caption, variable, pad=(0, 8)):
            box = ttk.Frame(parent, style="Card.TFrame")
            box.grid(row=row, column=column, sticky="ew", padx=pad, pady=(0, 8))
            box.columnconfigure(0, weight=1)
            ttk.Label(box, text=caption, style="FieldLabel.TLabel").grid(
                row=0, column=0, sticky="w", pady=(0, 3)
            )
            ttk.Entry(box, textvariable=variable).grid(row=1, column=0, sticky="ew")
            return box

        field(rules, 0, 0, "AMOUNT TOLERANCE", self.amount_tolerance, (0, 8))
        field(rules, 0, 1, "DATE WINDOW (DAYS)", self.date_window, (8, 8))

        sign_box = ttk.Frame(rules, style="Card.TFrame")
        sign_box.grid(row=0, column=2, sticky="ew", padx=(8, 0), pady=(0, 8))
        sign_box.columnconfigure(0, weight=1)
        ttk.Label(sign_box, text="LEDGER SIGNS", style="FieldLabel.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 3)
        )
        ttk.Combobox(
            sign_box, textvariable=self.sign_convention, state="readonly",
            values=("auto", "same", "flip"),
        ).grid(row=1, column=0, sticky="ew")

        field(rules, 1, 0, "AUTO-MATCH ABOVE", self.match_threshold, (0, 8))
        field(rules, 1, 1, "REVIEW ABOVE", self.review_threshold, (8, 8))

        group_box = ttk.Frame(rules, style="Card.TFrame")
        group_box.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        ttk.Label(group_box, text="GROUPED MATCHES", style="FieldLabel.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        ToggleSwitch(
            group_box, variable=self.group_matching, palette=p, type_scale=t,
            text="Match one bank line against several ledger lines",
            surface=p.card,
        ).grid(row=1, column=0, sticky="w")

        # ----------------------------------------------------------- action
        action = ttk.Frame(root, style="Canvas.TFrame")
        action.grid(row=2, column=0, sticky="ew", padx=22, pady=(6, 4))
        action.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(
            action, mode="indeterminate", style="Thin.Horizontal.TProgressbar"
        )
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 16), pady=(4, 0))
        self.progress.grid_remove()          # only shown while a run is going

        self.open_button = RoundedButton(
            action, text="Open folder", command=self._open_output,
            palette=p, type_scale=t, kind="ghost", height=38, surface=p.canvas,
        )
        self.open_button.grid(row=0, column=1, padx=(0, 8))
        self.open_button.configure(state="disabled")

        self.run_button = RoundedButton(
            action, text="Reconcile", command=self._start,
            palette=p, type_scale=t, kind="accent", height=38,
            min_width=150, surface=p.canvas,
        )
        self.run_button.grid(row=0, column=2)

        # ----------------------------------------------------------- result
        result_card = Card(sheet, p)
        result_card.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 14))
        result = result_card.body()
        result.columnconfigure(0, weight=1)
        result.rowconfigure(3, weight=1)

        ttk.Label(result, text="Result", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        legend = ttk.Frame(result, style="Card.TFrame")
        legend.grid(row=1, column=0, sticky="w", pady=(8, 10))
        for index, (label, fill, foreground) in enumerate((
            ("Matched", p.ok_fill, p.ok),
            ("Grouped", p.info_fill, p.info),
            ("Needs review", p.warn_fill, p.warn),
            ("Unmatched", p.bad_fill, p.bad),
        )):
            Chip(legend, label, fill, foreground, t).grid(
                row=0, column=index, padx=(0, 6)
            )

        result_wrap = tk.Frame(
            result, background=p.card_border, bd=0, highlightthickness=0
        )
        result_wrap.grid(row=3, column=0, sticky="nsew")
        result_wrap.columnconfigure(0, weight=1)
        result_wrap.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            result_wrap, columns=("metric", "value"), show="headings", height=6
        )
        self.tree.heading("metric", text="SHEET / METRIC", anchor="w")
        self.tree.heading("value", text="RESULT", anchor="w")
        self.tree.column("metric", width=300, anchor="w", stretch=False)
        self.tree.column("value", width=430, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        result_scroll = AutoHideScrollbar(
            result_wrap, orient="vertical", command=self.tree.yview,
            style="Flat.Vertical.TScrollbar",
        )
        result_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 1), pady=1)
        self.tree.configure(yscrollcommand=result_scroll.set)
        self.tree.tag_configure("odd", background=p.stripe)
        self.tree.tag_configure("total", font=t.body_bold)

        # ----------------------------------------------------------- status
        ttk.Label(root, textvariable=self.status, style="Status.TLabel").grid(
            row=3, column=0, sticky="ew", padx=24, pady=(2, 14)
        )

        self._two_sheet_widgets = []
        self._apply_mode()
        self._restore_result_rows()

    # ------------------------------------------------------------- theming
    def _toggle_theme(self) -> None:
        """Swap light and dark, rebuilding the window in the new palette."""
        from .theme import PALETTES

        self.theme_name.set("dark" if self.theme_name.get() == "light" else "light")
        self.palette = PALETTES[self.theme_name.get()]
        self._rebuild()

    def _rebuild(self) -> None:
        """Tear the window down and lay it out again in the current palette."""
        for child in self.root.winfo_children():
            child.destroy()
        self._build()
        self._populate_sheet_tree()

    def _restore_result_rows(self) -> None:
        for index, (metric, value) in enumerate(self._result_rows):
            tags = ("total",) if metric == "TOTAL" else (("odd",) if index % 2 else ())
            self.tree.insert("", "end", values=(metric, value), tags=tags)
        if self._result_rows:
            self.open_button.configure(state="normal")

    def _show_results(self, rows: list[tuple[str, str]]) -> None:
        self._result_rows = rows
        self.tree.delete(*self.tree.get_children())
        self._restore_result_rows()

    def _on_rules_toggle(self, expanded: bool) -> None:
        """Keep the newly revealed settings in view."""
        self.root.update_idletasks()
        if expanded:
            self.scroller.canvas.yview_moveto(
                max(0.0, self.rules_card.winfo_y() / max(self.scroller.body.winfo_height(), 1))
            )

    LAYOUT_CAPTIONS = {
        "pack": "Each sheet holds both sides: ledger items above, bank items below.",
        "sheets": "One sheet is the bank statement, another is the ledger.",
    }

    def _apply_mode(self) -> None:
        """Show the controls that belong to the selected layout."""
        self.layout_caption.set(self.LAYOUT_CAPTIONS.get(self.mode.get(), ""))
        if self.mode.get() == "pack":
            self.sheets_frame.grid_remove()
            self.pack_frame.grid(row=8, column=0, sticky="ew", pady=(12, 0))
        else:
            self.pack_frame.grid_remove()
            self.sheets_frame.grid(row=8, column=0, sticky="ew", pady=(12, 0))
            self._toggle_separate_ledger()
        path = self.statement_path.get().strip()
        if path:
            self.output_path.set(default_output_path(path, self.mode.get()))

    def _toggle_separate_ledger(self) -> None:
        if self.mode.get() == "pack":
            return
        if self.separate_ledger_file.get():
            self.ledger_label.grid(row=2, column=0, sticky="w", pady=(10, 3))
            self.ledger_entry.grid(row=3, column=0, sticky="ew", padx=(0, 8))
            self.ledger_button.grid(row=3, column=1, sticky="w")
        else:
            self.ledger_label.grid_remove()
            self.ledger_entry.grid_remove()
            self.ledger_button.grid_remove()
            self.ledger_path.set(self.statement_path.get())
            if self.statement_path.get():
                self._load_sheets(self.statement_path.get(), which="both")

    # ------------------------------------------------------------- actions
    def _browse_statement(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(title="Choose the workbook", filetypes=SPREADSHEET_TYPES)
        if not path:
            return
        self.statement_path.set(path)
        self.output_path.set(default_output_path(path, self.mode.get()))
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

        total = len(self._findings)
        usable = sum(1 for v in self._findings.values() if " rows at sheet rows " in v)
        self.source_caption.set(
            f"{os.path.basename(path)}   ·   {total} sheet{'s' if total != 1 else ''}"
            + (f"   ·   {usable} ready to reconcile" if self.mode.get() == "pack" else "")
        )
        if self.mode.get() == "pack":
            self.status.set(
                f"Detected a reconciliation pack. {usable} sheet"
                f"{'s' if usable != 1 else ''} ready - press Reconcile."
            )
        else:
            self.ledger_path.set(path)
            self._load_sheets(path, which="both")

    def _populate_sheet_tree(self) -> None:
        self.sheet_tree.delete(*self.sheet_tree.get_children())
        for index, (sheet, finding) in enumerate(self._findings.items()):
            usable = " rows at sheet rows " in finding
            tags = []
            if index % 2:
                tags.append("odd")
            if not usable:
                tags.append("skip")
            pretty = finding
            if usable:
                # "SAP: 26 rows ... / Bank Statement: 26 rows ..." is what the
                # detector reports; keep it short enough to read at a glance.
                pretty = finding.replace(" rows at sheet rows ", " rows, lines ")
            self.sheet_tree.insert(
                "", "end", iid=sheet, values=(sheet, pretty), tags=tuple(tags)
            )

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
        self.progress.grid()
        self.progress.start(12)
        self.status.set("Reconciling...  this can take a moment on large statements.")
        self._result_rows = []
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

    def _cancel_polling(self) -> None:
        self._closing = True
        if self._poll_id is not None:
            try:
                self.root.after_cancel(self._poll_id)
            except Exception:  # noqa: BLE001 - already torn down
                pass
            self._poll_id = None

    def _on_destroy(self, event) -> None:
        if event.widget is self.root:
            self._cancel_polling()

    def close(self) -> None:
        """Shut the window down cleanly.

        A pending ``after`` callback that outlives the widget makes Tcl print
        "invalid command name" on exit, which reads as a crash.
        """
        self._cancel_polling()
        try:
            self.root.destroy()
        except Exception:  # noqa: BLE001 - already gone
            pass

    def _drain_queue(self) -> None:
        import tkinter as tk

        if self._closing:
            return
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return          # the window was destroyed without going through _on_close
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
            try:
                if not self._closing and self.root.winfo_exists():
                    self._poll_id = self.root.after(100, self._drain_queue)
            except tk.TclError:
                pass

    def _on_success(self, result: ReconciliationResult, output: str) -> None:
        self.progress.stop()
        self.progress.grid_remove()
        self.run_button.configure(state="normal")
        self.open_button.configure(state="normal")
        self._last_output = output
        self._show_results([(str(k), str(v)) for k, v in result.summary.items()])
        self.status.set(f"Done  ·  coloured workbook saved to {os.path.basename(output)}")

    def _on_pack_success(self, outcome: PackOutcome, output: str) -> None:
        self.progress.stop()
        self.progress.grid_remove()
        self.run_button.configure(state="normal")
        self.open_button.configure(state="normal")
        self._last_output = output

        rows: list[tuple[str, str]] = []
        for sheet_outcome in outcome.sheets:
            if not sheet_outcome.ok:
                rows.append((sheet_outcome.sheet, f"skipped - {sheet_outcome.skipped}"))
                continue
            counts = sheet_outcome.counts
            rows.append((
                sheet_outcome.sheet,
                f"{counts['matched'] + counts['grouped']} matched   ·   "
                f"{counts['review']} to review   ·   "
                f"{counts['unmatched_ledger'] + counts['unmatched_bank']} still open",
            ))
        totals = outcome.totals
        rows.append((
            "TOTAL",
            f"{totals['matched'] + totals['grouped']} matched   ·   "
            f"{totals['review']} to review   ·   "
            f"{totals['unmatched_ledger'] + totals['unmatched_bank']} still open",
        ))
        self._show_results(rows)
        self.status.set(f"Done  ·  marked copy saved to {os.path.basename(output)}")

    def _on_error(self, error: Exception, detail: str) -> None:
        from tkinter import messagebox

        self.progress.stop()
        self.progress.grid_remove()
        self.run_button.configure(state="normal")
        self.status.set("Reconciliation failed - see the message for details.")
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
