"""Allow ``python -m bank_reconciliation``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
