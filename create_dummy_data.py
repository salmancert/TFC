#!/usr/bin/env python3
"""Create a sample statement/ledger workbook to try the reconciler on.

    python create_dummy_data.py [output.xlsx]
"""

from __future__ import annotations

import sys

from bank_reconciliation.sample_data import write_sample_workbook

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "test_reconciliation.xlsx"
    print(f"Created {write_sample_workbook(target)}")
