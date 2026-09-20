"""Write a colour-coded copy of the source data.

The output workbook keeps both original sheets exactly as supplied and
paints every row with the verdict the reconciler reached, so the result can
be read at a glance without cross-referencing a separate report:

    green   - matched automatically
    blue    - matched, but one bank line settles several ledger lines
    amber   - a likely match that a human should confirm
    red     - nothing on the other side explains this row

Each matched row also gets a ``Match ID`` so the two sides can be lined up,
and a legend sheet explains the colours to whoever opens the file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .matcher import ReconciliationResult
from .report import build_frames

# Fills are deliberately pale: the cell text must stay readable, and these
# survive both light and dark spreadsheet themes.
FILL_MATCHED = PatternFill("solid", start_color="C6EFCE", end_color="C6EFCE")
FILL_GROUPED = PatternFill("solid", start_color="BDD7EE", end_color="BDD7EE")
FILL_REVIEW = PatternFill("solid", start_color="FFEB9C", end_color="FFEB9C")
FILL_UNMATCHED = PatternFill("solid", start_color="FFC7CE", end_color="FFC7CE")
FILL_HEADER = PatternFill("solid", start_color="44546A", end_color="44546A")

FONT_MATCHED = Font(color="006100")
FONT_GROUPED = Font(color="1F4E79")
FONT_REVIEW = Font(color="9C6500")
FONT_UNMATCHED = Font(color="9C0006")
FONT_HEADER = Font(color="FFFFFF", bold=True)

LEGEND = [
    ("matched", "Matched automatically", FILL_MATCHED, FONT_MATCHED),
    ("grouped", "Matched as a group (one bank line, several ledger lines)",
     FILL_GROUPED, FONT_GROUPED),
    ("review", "Likely match - please confirm", FILL_REVIEW, FONT_REVIEW),
    ("unmatched", "No counterpart found", FILL_UNMATCHED, FONT_UNMATCHED),
]

_STYLES = {
    "matched": (FILL_MATCHED, FONT_MATCHED),
    "grouped": (FILL_GROUPED, FONT_GROUPED),
    "review": (FILL_REVIEW, FONT_REVIEW),
    "unmatched": (FILL_UNMATCHED, FONT_UNMATCHED),
}

ADDED_COLUMNS = ("Match ID", "Match Status", "Confidence", "Matched With")


@dataclass
class RowVerdict:
    """The decision attached to a single source row."""

    style: str            # key into _STYLES
    match_id: str = ""
    confidence: float | None = None
    partner: str = ""


def _verdicts(result: ReconciliationResult) -> tuple[dict[int, RowVerdict], dict[int, RowVerdict]]:
    """Map every row on both sides to the verdict that should colour it."""
    left_verdicts: dict[int, RowVerdict] = {}
    right_verdicts: dict[int, RowVerdict] = {}

    for number, record in enumerate(result.records, start=1):
        match_id = f"M{number:04d}"
        style = "review" if record.status == "review" else (
            "grouped" if record.kind == "grouped" else "matched"
        )
        left_label = ", ".join(str(row + 2) for row in record.left_rows)
        right_label = ", ".join(str(row + 2) for row in record.right_rows)
        for row in record.left_rows:
            left_verdicts[row] = RowVerdict(
                style, match_id, record.score, f"{result.right.name} row {right_label}"
            )
        for row in record.right_rows:
            right_verdicts[row] = RowVerdict(
                style, match_id, record.score, f"{result.left.name} row {left_label}"
            )

    for row in result.unmatched_left:
        left_verdicts[row] = RowVerdict("unmatched")
    for row in result.unmatched_right:
        right_verdicts[row] = RowVerdict("unmatched")
    return left_verdicts, right_verdicts


def _autosize(sheet: Worksheet, frame: pd.DataFrame, max_width: int = 46) -> None:
    for position, column in enumerate(frame.columns, start=1):
        widest = max(
            [len(str(column))] + [len(str(value)) for value in frame[column].head(200)]
        )
        sheet.column_dimensions[get_column_letter(position)].width = min(widest + 2, max_width)


def _style_header(sheet: Worksheet, n_columns: int) -> None:
    for position in range(1, n_columns + 1):
        cell = sheet.cell(row=1, column=position)
        cell.fill = FILL_HEADER
        cell.font = FONT_HEADER
        cell.alignment = Alignment(vertical="center")
    sheet.freeze_panes = "A2"


def _write_marked_sheet(
    writer: pd.ExcelWriter,
    sheet_name: str,
    frame: pd.DataFrame,
    verdicts: dict[int, RowVerdict],
) -> None:
    """Write one source sheet with the verdict columns appended and coloured."""
    marked = frame.copy()
    marked["Match ID"] = [verdicts.get(i, RowVerdict("unmatched")).match_id for i in range(len(frame))]
    marked["Match Status"] = [
        verdicts.get(i, RowVerdict("unmatched")).style for i in range(len(frame))
    ]
    marked["Confidence"] = [
        (round(verdicts[i].confidence, 3) if i in verdicts and verdicts[i].confidence is not None
         else None)
        for i in range(len(frame))
    ]
    marked["Matched With"] = [
        verdicts.get(i, RowVerdict("unmatched")).partner for i in range(len(frame))
    ]

    marked.to_excel(writer, sheet_name=sheet_name, index=False)
    sheet = writer.sheets[sheet_name]
    n_columns = len(marked.columns)
    _style_header(sheet, n_columns)

    thin = Side(style="thin", color="FFFFFF")
    for row_index in range(len(marked)):
        verdict = verdicts.get(row_index, RowVerdict("unmatched"))
        fill, font = _STYLES[verdict.style]
        for position in range(1, n_columns + 1):
            cell = sheet.cell(row=row_index + 2, column=position)
            cell.fill = fill
            cell.font = font
            cell.border = Border(bottom=thin)

    _autosize(sheet, marked)
    if len(marked):
        sheet.auto_filter.ref = (
            f"A1:{get_column_letter(n_columns)}{len(marked) + 1}"
        )


def _write_legend(writer: pd.ExcelWriter, result: ReconciliationResult) -> None:
    frame = pd.DataFrame(
        [{"Colour": style, "Meaning": meaning} for style, meaning, _, _ in LEGEND]
    )
    frame.to_excel(writer, sheet_name="Legend", index=False)
    sheet = writer.sheets["Legend"]
    _style_header(sheet, 2)
    for offset, (_, _, fill, font) in enumerate(LEGEND, start=2):
        for column in (1, 2):
            cell = sheet.cell(row=offset, column=column)
            cell.fill = fill
            cell.font = font
    sheet.column_dimensions["A"].width = 14
    sheet.column_dimensions["B"].width = 62

    start = len(LEGEND) + 4
    sheet.cell(row=start, column=1, value="Summary").font = Font(bold=True)
    for offset, (key, value) in enumerate(result.summary.items(), start=start + 1):
        sheet.cell(row=offset, column=1, value=str(key))
        sheet.cell(row=offset, column=2, value=str(value))


def write_highlighted_workbook(result: ReconciliationResult, path: str) -> str:
    """Write the colour-coded workbook, plus the tabular report sheets."""
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)

    left_verdicts, right_verdicts = _verdicts(result)
    frames = build_frames(result)

    with pd.ExcelWriter(path, engine="openpyxl", mode="w") as writer:
        _write_legend(writer, result)
        _write_marked_sheet(
            writer, _sheet_name(result.left.name), result.left.frame, left_verdicts
        )
        _write_marked_sheet(
            writer, _sheet_name(result.right.name), result.right.frame, right_verdicts
        )
        matches = frames["Matches"]
        matches.to_excel(writer, sheet_name="Matches", index=False)
        _style_header(writer.sheets["Matches"], max(len(matches.columns), 1))
        _autosize(writer.sheets["Matches"], matches)
    return path


def _sheet_name(name: str, limit: int = 31) -> str:
    cleaned = str(name).replace("[", "(").replace("]", ")")
    for character in ":*?/\\":
        cleaned = cleaned.replace(character, "_")
    return (cleaned.strip() or "Sheet")[:limit]
