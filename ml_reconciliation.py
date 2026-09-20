#!/usr/bin/env python3
"""Backwards-compatible wrapper around the :mod:`bank_reconciliation` package.

The original version of this script matched rows by running TF-IDF over
every column joined into one string, which treated amounts and dates as
text, let several statement lines claim the same ledger line, reported a
"match" for every row no matter how poor, and wrote its results back into
the file it had just read.  All of that now lives in a proper package:

    python -m bank_reconciliation statement.xlsx     # command line
    python reconcile_gui.py                          # desktop app

This entry point is kept so existing commands keep working.
"""

from __future__ import annotations

import sys

from bank_reconciliation.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
