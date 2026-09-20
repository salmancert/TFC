"""Command line entry point for the reconciler."""

from __future__ import annotations

import argparse
import logging
import os
import sys

import pandas as pd

from .matcher import ReconciliationConfig, reconcile
from .model import load_scorer, save_scorer
from .highlight import write_highlighted_workbook
from .report import format_console_report, write_csvs, write_excel

LOGGER = logging.getLogger("bank_reconciliation")


def _read_table(path: str, sheet: str | int | None) -> tuple[pd.DataFrame, str]:
    """Read one table from a CSV or from a named/positional Excel sheet."""
    extension = os.path.splitext(path)[1].lower()
    if extension in {".csv", ".txt", ".tsv"}:
        separator = "\t" if extension == ".tsv" else ","
        frame = pd.read_csv(path, sep=separator)
        return frame, os.path.splitext(os.path.basename(path))[0]

    book = pd.ExcelFile(path)
    if sheet is None:
        sheet = 0
    if isinstance(sheet, str) and sheet not in book.sheet_names:
        raise SystemExit(
            f"Sheet {sheet!r} not found in {path}. Available sheets: {book.sheet_names}"
        )
    name = sheet if isinstance(sheet, str) else book.sheet_names[sheet]
    return book.parse(name), str(name)


def _default_sheets(path: str, requested: list[str] | None) -> tuple[object, object]:
    """Work out which two sheets to compare, skipping our own output sheets."""
    if requested:
        if len(requested) != 2:
            raise SystemExit("--sheets takes exactly two sheet names")
        return requested[0], requested[1]

    if os.path.splitext(path)[1].lower() in {".csv", ".txt", ".tsv"}:
        return 0, 0

    names = pd.ExcelFile(path).sheet_names
    generated = {"summary", "matches"}
    usable = [
        name for name in names
        if name.lower() not in generated
        and not name.lower().startswith(("unmatched_", "ml_reconciliation"))
    ]
    if len(usable) < 2:
        raise SystemExit(
            f"{path} needs at least two data sheets to reconcile (found: {names})"
        )
    return usable[0], usable[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bank-reconcile",
        description=(
            "Reconcile a bank statement against an internal ledger using "
            "machine-learned match scoring."
        ),
    )
    parser.add_argument("statement", help="Excel workbook or CSV holding the bank statement")
    parser.add_argument(
        "--ledger",
        help="Second file holding the ledger. Omit to use a second sheet of the first file.",
    )
    parser.add_argument(
        "--sheets",
        nargs="+",
        metavar="SHEET",
        help="Sheet names to compare. Two names when reading one workbook, one per file otherwise.",
    )
    parser.add_argument(
        "-o", "--output",
        help="Where to write the report (default: <statement>_reconciliation.xlsx)",
    )
    parser.add_argument(
        "--tables",
        action="store_true",
        help="Write plain report tables instead of a colour-coded copy of the data.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Append the report tables to the input workbook instead of writing a new file.",
    )
    parser.add_argument("--csv-dir", help="Also write each report table as a CSV here.")

    matching = parser.add_argument_group("matching policy")
    matching.add_argument("--amount-tolerance", type=float, default=0.01,
                          help="Absolute amount difference still treated as equal (default: 0.01)")
    matching.add_argument("--date-window", type=int, default=5,
                          help="Days either side still considered the same transaction (default: 5)")
    matching.add_argument("--match-threshold", type=float, default=0.60,
                          help="Confidence at or above which a match is accepted (default: 0.60)")
    matching.add_argument("--review-threshold", type=float, default=0.35,
                          help="Confidence below which a pair is discarded (default: 0.35)")
    matching.add_argument("--sign", choices=("auto", "same", "flip"), default="auto",
                          help="Sign convention of the ledger relative to the statement")
    matching.add_argument("--no-group-matching", action="store_true",
                          help="Disable one-to-many (batch deposit) matching")
    matching.add_argument("--max-group-size", type=int, default=3,
                          help="Largest number of ledger rows allowed in a grouped match")

    model = parser.add_argument_group("scoring model")
    model.add_argument("--load-model", help="Reuse a scorer previously saved with --save-model")
    model.add_argument("--save-model", help="Save the scorer trained on this run to this path")
    model.add_argument("--prior-weight", type=float, default=0.25,
                       help="How much fixed heuristic to blend into the learned score (0-1)")

    parser.add_argument("-q", "--quiet", action="store_true", help="Only report errors")
    parser.add_argument("-v", "--verbose", action="store_true", help="Explain what is happening")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.ERROR if args.quiet else (logging.DEBUG if args.verbose else logging.INFO),
        format="%(message)s",
    )

    if not os.path.exists(args.statement):
        LOGGER.error("File not found: %s", args.statement)
        return 2
    if args.ledger and not os.path.exists(args.ledger):
        LOGGER.error("File not found: %s", args.ledger)
        return 2

    try:
        if args.ledger:
            left_sheet = args.sheets[0] if args.sheets else None
            right_sheet = (
                args.sheets[1] if args.sheets and len(args.sheets) > 1 else None
            )
            left_frame, left_name = _read_table(args.statement, left_sheet)
            right_frame, right_name = _read_table(args.ledger, right_sheet)
        else:
            left_sheet, right_sheet = _default_sheets(args.statement, args.sheets)
            left_frame, left_name = _read_table(args.statement, left_sheet)
            right_frame, right_name = _read_table(args.statement, right_sheet)
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001 - surfaced to the user verbatim
        LOGGER.error("Could not read the input data: %s", error)
        return 2

    if left_name == right_name:
        left_name, right_name = f"{left_name}_A", f"{right_name}_B"

    config = ReconciliationConfig(
        amount_tolerance=args.amount_tolerance,
        date_window_days=args.date_window,
        match_threshold=args.match_threshold,
        review_threshold=args.review_threshold,
        sign_convention=args.sign,
        group_matching=not args.no_group_matching,
        max_group_size=args.max_group_size,
        prior_weight=args.prior_weight,
    )
    try:
        config.validate()
    except ValueError as error:
        LOGGER.error("%s", error)
        return 2

    scorer = load_scorer(args.load_model) if args.load_model else None

    LOGGER.info("Reconciling %r against %r ...", left_name, right_name)
    result = reconcile(
        left_frame, right_frame, left_name, right_name, config=config, scorer=scorer
    )

    if args.in_place:
        output = args.statement
        write_excel(result, output, append=True)
    elif args.tables:
        output = args.output or f"{os.path.splitext(args.statement)[0]}_reconciliation.xlsx"
        write_excel(result, output, append=False)
    else:
        output = args.output or f"{os.path.splitext(args.statement)[0]}_reconciled.xlsx"
        if os.path.abspath(output) == os.path.abspath(args.statement):
            LOGGER.error("The output would overwrite the input file; pass -o with another name.")
            return 2
        write_highlighted_workbook(result, output)

    if args.csv_dir:
        write_csvs(result, args.csv_dir)

    if not args.quiet:
        print(format_console_report(result))
        print(f"\nReport written to {output}")

    if args.save_model:
        if not result.scorer.is_learned:
            LOGGER.warning(
                "No model could be trained on this run (%s); nothing saved to %s",
                result.training.reason or "heuristic fallback",
                args.save_model,
            )
        else:
            save_scorer(result.scorer, args.save_model)
            LOGGER.info("Scorer saved to %s", args.save_model)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
