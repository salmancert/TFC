"""Split a reconciliation pack that holds both sides in one sheet.

An outsourced provider typically delivers one sheet per account: a title
block, a balance line, the open items from the accounting system, the open
items from the bank statement, and a footer.  Everything arrives flagged as
unmatched and the client is expected to mark it up.

This module finds those two blocks inside the raw sheet, hands each one
back as a table, and remembers which spreadsheet row every table row came
from so the marking can be written back onto the original pack.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .schema import (
    AMOUNT_NAME_HINTS,
    DATE_NAME_HINTS,
    DESCRIPTION_NAME_HINTS,
    REFERENCE_NAME_HINTS,
    parse_amount_series,
)

LOGGER = logging.getLogger(__name__)

# Words naming the accounting-system side of a reconciliation.
LEDGER_WORDS = (
    "sap", "gl", "g/l", "general ledger", "ledger", "book", "books",
    "cash book", "cashbook", "erp", "system", "our records", "company",
)
# Words naming the bank side.
BANK_WORDS = ("bank", "statement", "bank statement", "per bank")
# Words that mark a block of reconciling items rather than a balance line.
SECTION_WORDS = (
    "unmatched", "unidentified", "unreconciled", "outstanding", "open item",
    "open items", "not matched", "reconciling", "uncleared", "unpresented",
    "in transit", "deposit in transit",
)
# Rows that look like section headings but are really totals.
TOTAL_WORDS = ("balance", "total", "subtotal", "sum of", "closing", "opening", "difference")

HEADER_HINTS = tuple(
    set(DATE_NAME_HINTS) | set(AMOUNT_NAME_HINTS)
    | set(DESCRIPTION_NAME_HINTS) | set(REFERENCE_NAME_HINTS)
)


@dataclass
class Section:
    """One block of open items inside a single-sheet pack."""

    label: str
    frame: pd.DataFrame
    source_rows: list[int]      # 0-based row index into the raw sheet
    header_row: int | None = None
    marker_row: int | None = None
    marker_text: str = ""

    def __len__(self) -> int:
        return len(self.frame)

    @property
    def first_excel_row(self) -> int:
        return (self.source_rows[0] + 1) if self.source_rows else 0

    @property
    def last_excel_row(self) -> int:
        return (self.source_rows[-1] + 1) if self.source_rows else 0

    def describe(self) -> str:
        return (
            f"{self.label}: {len(self.frame)} rows at sheet rows "
            f"{self.first_excel_row}-{self.last_excel_row}"
        )


@dataclass
class SheetLayout:
    """What was found inside a single-sheet pack."""

    raw: pd.DataFrame
    sections: list[Section] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def is_pack(self) -> bool:
        """True when two usable blocks of open items were identified."""
        return len(self.sections) == 2 and all(len(s) > 0 for s in self.sections)


def _row_text(raw: pd.DataFrame, row: int) -> str:
    values = [
        str(value).strip()
        for value in raw.iloc[row].tolist()
        if value is not None and not (isinstance(value, float) and np.isnan(value))
    ]
    return " ".join(v for v in values if v and v.lower() != "nan").strip()


def _is_blank(raw: pd.DataFrame, row: int) -> bool:
    return _row_text(raw, row) == ""


def _numeric_cells(raw: pd.DataFrame, row: int) -> int:
    parsed = parse_amount_series(pd.Series(raw.iloc[row].tolist(), dtype=object))
    return int(parsed.notna().sum())


def _contains(text: str, words: tuple[str, ...]) -> bool:
    padded = f" {re.sub(r'[^a-z0-9/ ]+', ' ', text.lower())} "
    padded = re.sub(r"\s+", " ", padded)
    return any(f" {word} " in padded for word in words)


def side_of(text: str) -> str | None:
    """Which side of the reconciliation a heading names, if it says."""
    ledger = _contains(text, LEDGER_WORDS)
    bank = _contains(text, BANK_WORDS)
    if ledger and not bank:
        return "ledger"
    if bank and not ledger:
        return "bank"
    if ledger and bank:
        # e.g. "Items in SAP not on the bank statement" - the first one wins.
        lowered = text.lower()
        first_ledger = min((lowered.find(w) for w in LEDGER_WORDS if w in lowered), default=10**6)
        first_bank = min((lowered.find(w) for w in BANK_WORDS if w in lowered), default=10**6)
        return "ledger" if first_ledger <= first_bank else "bank"
    return None


def _is_header_row(raw: pd.DataFrame, row: int) -> bool:
    """A row of column captions rather than data."""
    cells = [
        re.sub(r"[^a-z0-9 ]+", " ", str(value).lower()).strip()
        for value in raw.iloc[row].tolist()
        if value is not None and str(value).strip() and str(value).lower() != "nan"
    ]
    if len(cells) < 2:
        return False
    hits = sum(
        1 for cell in cells
        if any(hint in cell or cell in hint for hint in HEADER_HINTS)
    )
    return hits >= 2 and _numeric_cells(raw, row) == 0


def _is_total_row(raw: pd.DataFrame, row: int) -> bool:
    """A balance or total line: a caption, then a figure."""
    text = _row_text(raw, row).strip().lower()
    if not text:
        return False
    return any(text.startswith(word) for word in TOTAL_WORDS)


def _is_data_row(raw: pd.DataFrame, row: int) -> bool:
    """A row carrying an actual open item."""
    if _is_blank(raw, row) or _is_header_row(raw, row) or _is_total_row(raw, row):
        return False
    populated = sum(
        1 for value in raw.iloc[row].tolist()
        if value is not None and str(value).strip() and str(value).lower() != "nan"
    )
    return _numeric_cells(raw, row) >= 1 and populated >= 2


def _is_section_marker(raw: pd.DataFrame, row: int, strict: bool = False) -> bool:
    """A heading that introduces a block of open items.

    ``strict`` requires the heading to name the items ("unmatched",
    "outstanding", ...) rather than merely mentioning a side, which keeps a
    sheet title such as "Bank Reconciliation Statement" from being read as
    the start of a block.
    """
    text = _row_text(raw, row)
    if not text or _numeric_cells(raw, row) > 0:
        return False           # balance and total lines carry a figure
    if _contains(text, TOTAL_WORDS):
        return False
    if _is_header_row(raw, row):
        return False
    if _contains(text, SECTION_WORDS):
        return True
    return (not strict) and side_of(text) is not None


def _columns_for(raw: pd.DataFrame, header_row: int | None) -> list[str]:
    if header_row is None:
        return [f"Column {i + 1}" for i in range(raw.shape[1])]
    names: list[str] = []
    for position, value in enumerate(raw.iloc[header_row].tolist()):
        caption = "" if value is None else str(value).strip()
        if not caption or caption.lower() == "nan":
            caption = f"Column {position + 1}"
        while caption in names:
            caption = f"{caption}_{position + 1}"
        names.append(caption)
    return names


def _build_section(
    raw: pd.DataFrame,
    data_rows: list[int],
    header_row: int | None,
    label: str,
    marker_row: int | None,
    marker_text: str,
) -> Section:
    frame = raw.iloc[data_rows].copy()
    frame.columns = _columns_for(raw, header_row)
    # Drop columns that are empty right through this block.
    keep = [
        column for column in frame.columns
        if frame[column].map(
            lambda v: v is not None and str(v).strip() != "" and str(v).lower() != "nan"
        ).any()
    ]
    frame = frame[keep].reset_index(drop=True)
    return Section(
        label=label,
        frame=frame,
        source_rows=list(data_rows),
        header_row=header_row,
        marker_row=marker_row,
        marker_text=marker_text,
    )


def _contiguous_runs(rows: list[int], max_gap: int = 2) -> list[list[int]]:
    """Group row indices into blocks separated by more than ``max_gap`` rows."""
    runs: list[list[int]] = []
    for row in rows:
        if runs and row - runs[-1][-1] <= max_gap:
            runs[-1].append(row)
        else:
            runs.append([row])
    return runs


def detect_layout(raw: pd.DataFrame) -> SheetLayout:
    """Find the two blocks of open items in a single-sheet pack."""
    raw = raw.reset_index(drop=True)
    layout = SheetLayout(raw=raw)
    if raw.empty:
        layout.notes.append("The sheet is empty.")
        return layout

    n_rows = len(raw)
    data_rows = [row for row in range(n_rows) if _is_data_row(raw, row)]
    header_rows = [row for row in range(n_rows) if _is_header_row(raw, row)]
    # Headings that name the items are the reliable ones; fall back to any
    # heading that merely names a side only if there are not two of those.
    markers = [row for row in range(n_rows) if _is_section_marker(raw, row, strict=True)]
    if len(markers) < 2:
        markers = [row for row in range(n_rows) if _is_section_marker(raw, row)]

    if not data_rows:
        layout.notes.append("No rows with an amount were found.")
        return layout

    def header_above(row: int, floor: int) -> int | None:
        candidates = [h for h in header_rows if floor <= h < row]
        return candidates[-1] if candidates else None

    blocks: list[tuple[list[int], int | None, int | None]] = []

    # --- preferred: explicit section headings --------------------------------
    if len(markers) >= 2:
        bounds = markers + [n_rows]
        for position, marker in enumerate(markers):
            span = [r for r in data_rows if marker < r < bounds[position + 1]]
            if span:
                blocks.append((span, header_above(span[0], marker), marker))
        if len(blocks) > 2:
            # Keep the two biggest blocks; stray headings happen.
            blocks = sorted(blocks, key=lambda b: -len(b[0]))[:2]
            blocks.sort(key=lambda b: b[0][0])
            layout.notes.append(
                "More than two sections were found; used the two largest."
            )

    # --- fallback: split on the blank gap between the blocks -----------------
    if len(blocks) != 2:
        runs = _contiguous_runs(data_rows)
        if len(runs) > 2:
            gaps = [
                (runs[i + 1][0] - runs[i][-1], i)
                for i in range(len(runs) - 1)
            ]
            _, split_at = max(gaps)
            merged = [
                [row for run in runs[: split_at + 1] for row in run],
                [row for run in runs[split_at + 1:] for row in run],
            ]
            runs = merged
            layout.notes.append(
                "No section headings found; split at the largest gap between blocks."
            )
        elif len(runs) == 2:
            layout.notes.append("No section headings found; split on the blank row between blocks.")
        if len(runs) == 2:
            blocks = [
                (run, header_above(run[0], 0 if index == 0 else runs[0][-1]), None)
                for index, run in enumerate(runs)
            ]

    if len(blocks) != 2:
        layout.notes.append(
            "Could not identify two separate blocks of items in this sheet."
        )
        return layout

    # --- label the two sides -------------------------------------------------
    labels: list[str] = []
    for rows, _, marker in blocks:
        text = _row_text(raw, marker) if marker is not None else ""
        side = side_of(text) if text else None
        labels.append(side or "")
    if labels[0] == labels[1] or not all(labels):
        # Packs conventionally list the accounting side first.
        labels = ["ledger", "bank"]
        layout.notes.append("Section sides were not named; assumed ledger first, bank second.")

    pretty = {"ledger": "SAP", "bank": "Bank Statement"}
    for (rows, header_row, marker), side in zip(blocks, labels):
        text = _row_text(raw, marker) if marker is not None else ""
        layout.sections.append(
            _build_section(raw, rows, header_row, pretty.get(side, side), marker, text)
        )
    return layout


def read_grid(path: str, sheet: str | int = 0) -> pd.DataFrame:
    """Read a sheet as a raw grid where frame row i is spreadsheet row i + 1.

    Excel is read through openpyxl rather than pandas so that blank rows,
    which pandas is free to drop depending on the reader and the format, can
    never shift the mapping back onto the original file.
    """
    if str(path).lower().endswith((".csv", ".txt", ".tsv")):
        separator = "\t" if str(path).lower().endswith(".tsv") else ","
        # skip_blank_lines defaults to True and would break the row mapping.
        return pd.read_csv(
            path, header=None, dtype=object, sep=separator, skip_blank_lines=False
        )

    import openpyxl

    book = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        worksheet = book[sheet] if isinstance(sheet, str) else book[book.sheetnames[sheet]]
        rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
    finally:
        book.close()
    if not rows:
        return pd.DataFrame()
    width = max(len(row) for row in rows)
    rows = [row + [None] * (width - len(row)) for row in rows]
    return pd.DataFrame(rows, dtype=object)


def read_pack(path: str, sheet: str | int = 0) -> SheetLayout:
    """Read a single-sheet pack straight off disk, keeping every row."""
    return detect_layout(read_grid(path, sheet))
