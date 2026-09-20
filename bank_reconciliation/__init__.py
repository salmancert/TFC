"""Machine-learning assisted bank reconciliation.

Matches a bank statement against an internal ledger by scoring candidate
row pairs on amount, date, narrative and reference evidence, then solving
for the best overall set of pairings.

Typical use::

    from bank_reconciliation import reconcile, write_excel

    result = reconcile(bank_df, ledger_df, "Bank", "Ledger")
    print(result.summary)
    write_excel(result, "reconciliation_report.xlsx")
"""

from .features import FEATURE_NAMES
from .matcher import (
    MatchRecord,
    ReconciliationConfig,
    ReconciliationResult,
    reconcile,
)
from .model import PairScorer, load_scorer, save_scorer, train_self_supervised
from .report import (
    build_frames,
    format_console_report,
    write_csvs,
    write_excel,
)
from .schema import ColumnRoles, NormalizedTable, detect_roles, normalize_table

__version__ = "1.0.0"

__all__ = [
    "FEATURE_NAMES",
    "ColumnRoles",
    "MatchRecord",
    "NormalizedTable",
    "PairScorer",
    "ReconciliationConfig",
    "ReconciliationResult",
    "build_frames",
    "detect_roles",
    "format_console_report",
    "load_scorer",
    "normalize_table",
    "reconcile",
    "save_scorer",
    "train_self_supervised",
    "write_csvs",
    "write_excel",
]
