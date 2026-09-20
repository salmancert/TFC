"""Render a :class:`ReconciliationResult` into reviewable tables."""

from __future__ import annotations

import os
import re

import numpy as np
import pandas as pd

from .matcher import ReconciliationResult

EXCEL_SHEET_LIMIT = 31


def _safe_sheet_name(name: str, used: set[str]) -> str:
    cleaned = re.sub(r"[\[\]:*?/\\]", "_", str(name)).strip() or "Sheet"
    cleaned = cleaned[:EXCEL_SHEET_LIMIT]
    candidate, counter = cleaned, 2
    while candidate.lower() in used:
        suffix = f"_{counter}"
        candidate = cleaned[: EXCEL_SHEET_LIMIT - len(suffix)] + suffix
        counter += 1
    used.add(candidate.lower())
    return candidate


def _join(values: list[object]) -> object:
    """Collapse the several ledger rows behind a grouped match into one cell."""
    if len(values) == 1:
        return values[0]
    return " | ".join("" if v is None else str(v) for v in values)


def _excel_rows(rows: tuple[int, ...]) -> str:
    """Report positions as the spreadsheet row numbers a human would look at."""
    return ", ".join(str(row + 2) for row in rows)


def build_match_frame(result: ReconciliationResult) -> pd.DataFrame:
    """One row per reconciliation decision, with both sides side by side."""
    left, right = result.left, result.right
    left_amounts = left.amount.to_numpy(dtype=float)
    right_amounts = right.amount.to_numpy(dtype=float)
    left_dates = left.date.to_numpy(dtype="datetime64[ns]")
    right_dates = right.date.to_numpy(dtype="datetime64[ns]")

    records = []
    for record in result.records:
        row: dict[str, object] = {
            "Status": record.status,
            "Match_Type": record.kind,
            "Confidence": round(record.score, 4),
            f"{left.name}_Row": _excel_rows(record.left_rows),
            f"{right.name}_Row": _excel_rows(record.right_rows),
        }
        for column in left.frame.columns:
            row[f"{left.name}.{column}"] = _join(
                [left.frame.at[i, column] for i in record.left_rows]
            )
        for column in right.frame.columns:
            row[f"{right.name}.{column}"] = _join(
                [right.frame.at[j, column] for j in record.right_rows]
            )

        left_total = float(np.nansum(left_amounts[list(record.left_rows)]))
        right_total = float(np.nansum(right_amounts[list(record.right_rows)]))
        row["Amount_Difference"] = round(left_total - right_total, 4)

        left_date = left_dates[record.left_rows[0]]
        candidate_dates = [right_dates[j] for j in record.right_rows if not np.isnat(right_dates[j])]
        if np.isnat(left_date) or not candidate_dates:
            row["Date_Difference_Days"] = None
        else:
            gaps = [
                abs(float((d - left_date) / np.timedelta64(1, "D"))) for d in candidate_dates
            ]
            row["Date_Difference_Days"] = round(max(gaps), 2)

        for name, value in record.evidence.items():
            row[f"feature.{name}"] = round(float(value), 4)
        records.append(row)

    if not records:
        return pd.DataFrame(
            columns=[
                "Status", "Match_Type", "Confidence",
                f"{left.name}_Row", f"{right.name}_Row",
                "Amount_Difference", "Date_Difference_Days",
            ]
        )
    return pd.DataFrame(records)


def build_unmatched_frame(
    table_frame: pd.DataFrame, rows: list[int], name: str
) -> pd.DataFrame:
    """The rows of one side that nothing could be matched against."""
    if not rows:
        return pd.DataFrame(columns=[f"{name}_Row", *table_frame.columns])
    frame = table_frame.iloc[rows].copy()
    frame.insert(0, f"{name}_Row", [row + 2 for row in rows])
    return frame.reset_index(drop=True)


def build_summary_frame(result: ReconciliationResult) -> pd.DataFrame:
    summary = pd.DataFrame(
        [{"Metric": key, "Value": value} for key, value in result.summary.items()]
    )
    extras = [
        {"Metric": f"Columns used in {result.left.name}", "Value": result.left.roles.describe()},
        {"Metric": f"Columns used in {result.right.name}", "Value": result.right.roles.describe()},
    ]
    if result.training.coefficients:
        ranked = sorted(
            result.training.coefficients.items(), key=lambda item: -abs(item[1])
        )
        extras.append(
            {
                "Metric": "Learned feature weights",
                "Value": ", ".join(f"{name}={value:+.2f}" for name, value in ranked),
            }
        )
    return pd.concat([summary, pd.DataFrame(extras)], ignore_index=True)


def build_frames(result: ReconciliationResult) -> dict[str, pd.DataFrame]:
    """All output tables, keyed by the sheet name they should be written to."""
    return {
        "Summary": build_summary_frame(result),
        "Matches": build_match_frame(result),
        f"Unmatched_{result.left.name}": build_unmatched_frame(
            result.left.frame, result.unmatched_left, result.left.name
        ),
        f"Unmatched_{result.right.name}": build_unmatched_frame(
            result.right.frame, result.unmatched_right, result.right.name
        ),
    }


def write_excel(result: ReconciliationResult, path: str, append: bool = False) -> str:
    """Write the report to ``path``; ``append`` adds sheets to an existing book."""
    frames = build_frames(result)
    mode = "a" if append and os.path.exists(path) else "w"
    kwargs: dict[str, object] = {"engine": "openpyxl", "mode": mode}
    if mode == "a":
        kwargs["if_sheet_exists"] = "replace"

    used: set[str] = set()
    with pd.ExcelWriter(path, **kwargs) as writer:
        for name, frame in frames.items():
            frame.to_excel(writer, sheet_name=_safe_sheet_name(name, used), index=False)
    return path


def write_csvs(result: ReconciliationResult, directory: str) -> list[str]:
    """Write the same report as one CSV per table."""
    os.makedirs(directory, exist_ok=True)
    written = []
    for name, frame in build_frames(result).items():
        target = os.path.join(directory, f"{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}.csv")
        frame.to_csv(target, index=False)
        written.append(target)
    return written


def format_console_report(result: ReconciliationResult) -> str:
    """A short human-readable digest for the terminal."""
    lines = ["Reconciliation summary", "-" * 22]
    for key, value in result.summary.items():
        lines.append(f"  {key}: {value}")
    review = [record for record in result.records if record.status == "review"]
    if review:
        lines.append("")
        lines.append(f"Needs review ({len(review)}):")
        for record in review[:10]:
            lines.append(
                f"  {result.left.name} row {_excel_rows(record.left_rows)} "
                f"<-> {result.right.name} row {_excel_rows(record.right_rows)} "
                f"(confidence {record.score:.2f})"
            )
        if len(review) > 10:
            lines.append(f"  ... and {len(review) - 10} more")
    return "\n".join(lines)
