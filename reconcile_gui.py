#!/usr/bin/env python3
"""Launch the bank reconciliation desktop app.

    python reconcile_gui.py
"""

import sys

from bank_reconciliation.gui import main

if __name__ == "__main__":
    sys.exit(main())
