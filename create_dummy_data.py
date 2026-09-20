#!/usr/bin/env python3
"""Create sample data to try the reconciler on.

    python create_dummy_data.py                    # two-sheet statement/ledger
    python create_dummy_data.py --pack             # one sheet per bank
    python create_dummy_data.py --pack -o mine.xlsx
"""

from __future__ import annotations

import argparse

from bank_reconciliation.sample_data import write_sample_multi_bank_pack, write_sample_workbook

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate sample reconciliation data")
    parser.add_argument(
        "--pack",
        action="store_true",
        help="Generate a multi-bank reconciliation pack (one sheet per bank, "
             "ledger items above, bank items below) instead of two sheets.",
    )
    parser.add_argument("-o", "--output", help="Where to write the workbook")
    arguments = parser.parse_args()

    if arguments.pack:
        target, _ = write_sample_multi_bank_pack(arguments.output or "sample_bank_pack.xlsx")
    else:
        target = write_sample_workbook(arguments.output or "test_reconciliation.xlsx")
    print(f"Created {target}")
