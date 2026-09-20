"""Generate a realistic statement/ledger pair together with ground truth.

Real reconciliation files are hard rather than merely large: amounts repeat,
narratives are written by different systems, dates drift by a few days, some
rows only ever exist on one side, and a single bank line often settles
several ledger lines at once.  The generator reproduces all of those so the
matcher can be measured rather than eyeballed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

VENDORS = [
    ("Northwind Traders", "ACH DEBIT NORTHWIND TRADERS", "Payment - Northwind Traders Ltd"),
    ("Contoso Supplies", "ACH DEBIT CONTOSO SUPPLIES", "Contoso Supplies invoice"),
    ("Fabrikam Logistics", "WIRE OUT FABRIKAM LOGISTIC", "Fabrikam Logistics freight"),
    ("Adatum Cleaning", "POS DEBIT ADATUM CLEANING", "Adatum office cleaning"),
    ("Litware Hosting", "CARD PURCHASE LITWARE HOST", "Litware cloud hosting"),
    ("Proseware Legal", "ACH DEBIT PROSEWARE LEGAL", "Proseware legal fees"),
    ("Tailspin Travel", "CARD PURCHASE TAILSPIN TRVL", "Tailspin travel booking"),
    ("Wide World Importers", "WIRE OUT WIDE WORLD IMP", "Wide World Importers goods"),
    ("Fourth Coffee", "POS DEBIT FOURTH COFFEE", "Fourth Coffee pantry"),
    ("Graphic Design Inst", "ACH DEBIT GRAPHIC DESIGN", "Graphic Design Institute"),
]

CUSTOMERS = [
    ("Alpine Retail", "WIRE IN ALPINE RETAIL", "Invoice settled - Alpine Retail"),
    ("Blue Yonder Airlines", "WIRE IN BLUE YONDER AIR", "Blue Yonder Airlines receipt"),
    ("Coho Vineyard", "ACH CREDIT COHO VINEYARD", "Coho Vineyard payment received"),
    ("Trey Research", "WIRE IN TREY RESEARCH", "Trey Research settlement"),
]


@dataclass
class SampleData:
    """A generated statement/ledger pair and the answers for it."""

    bank: pd.DataFrame
    ledger: pd.DataFrame
    # bank row index -> the ledger row indices that genuinely settle it
    truth: dict[int, tuple[int, ...]] = field(default_factory=dict)

    @property
    def n_true_pairs(self) -> int:
        return len(self.truth)


def _money(rng: np.random.Generator, low: float, high: float) -> float:
    return round(float(rng.uniform(low, high)), 2)


def generate_sample(
    n_matched: int = 90,
    n_groups: int = 4,
    n_bank_only: int = 6,
    n_ledger_only: int = 6,
    n_duplicate_amounts: int = 8,
    seed: int = 7,
    flip_ledger_sign: bool = False,
) -> SampleData:
    """Build a statement and ledger whose correct pairing is known.

    Args:
        n_matched: one-to-one pairs present on both sides.
        n_groups: bank lines that settle several ledger lines at once.
        n_bank_only: statement rows with no ledger counterpart (timing gaps).
        n_ledger_only: ledger rows not yet on the statement.
        n_duplicate_amounts: pairs forced to share an amount with another pair,
            so that amount alone cannot identify the right partner.
        seed: makes the output reproducible.
        flip_ledger_sign: emit the ledger with the opposite sign convention.
    """
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2024-01-02")

    bank_rows: list[dict[str, object]] = []
    ledger_rows: list[dict[str, object]] = []
    truth: dict[int, tuple[int, ...]] = {}

    def add_bank(date: pd.Timestamp, description: str, amount: float, reference: str = "") -> int:
        bank_rows.append(
            {
                "Posting Date": date.strftime("%Y-%m-%d"),
                "Description": description,
                "Amount": amount,
                "Bank Reference": reference or f"BK{rng.integers(100000, 999999)}",
            }
        )
        return len(bank_rows) - 1

    def add_ledger(date: pd.Timestamp, description: str, amount: float, reference: str) -> int:
        ledger_rows.append(
            {
                "Entry Date": date.strftime("%d/%m/%Y"),
                "Memo": description,
                "Document No": reference,
                "Net Amount": -amount if flip_ledger_sign else amount,
            }
        )
        return len(ledger_rows) - 1

    duplicate_amounts = [
        _money(rng, 100.0, 400.0) for _ in range(max(n_duplicate_amounts // 2, 1))
    ]

    for index in range(n_matched):
        incoming = index % 7 == 0
        pool = CUSTOMERS if incoming else VENDORS
        name, bank_text, ledger_text = pool[int(rng.integers(len(pool)))]

        if index < n_duplicate_amounts:
            magnitude = duplicate_amounts[index % len(duplicate_amounts)]
        else:
            magnitude = _money(rng, 15.0, 9000.0)
        amount = magnitude if incoming else -magnitude

        bank_date = start + pd.Timedelta(days=int(rng.integers(0, 120)))
        # Ledger entries are booked around the statement date, not on it.
        ledger_date = bank_date + pd.Timedelta(days=int(rng.integers(-3, 4)))
        reference = f"INV-{2000 + index}"

        # Only some bank narratives carry the document number, as in real feeds.
        bank_description = bank_text
        if rng.random() < 0.35:
            bank_description = f"{bank_text} {reference}"

        bank_index = add_bank(bank_date, bank_description, amount)
        ledger_index = add_ledger(ledger_date, f"{ledger_text} {name}", amount, reference)
        truth[bank_index] = (ledger_index,)

    # One bank line settling several ledger lines (a batch payment run).
    for group in range(n_groups):
        name, bank_text, ledger_text = VENDORS[int(rng.integers(len(VENDORS)))]
        size = int(rng.integers(2, 4))
        parts = [_money(rng, 50.0, 1200.0) for _ in range(size)]
        total = round(sum(parts), 2)
        bank_date = start + pd.Timedelta(days=int(rng.integers(0, 120)))
        bank_index = add_bank(bank_date, f"{bank_text} BATCH RUN", -total)
        members = [
            add_ledger(
                bank_date + pd.Timedelta(days=int(rng.integers(-2, 3))),
                f"{ledger_text} {name}",
                -part,
                f"INV-{5000 + group * 10 + position}",
            )
            for position, part in enumerate(parts)
        ]
        truth[bank_index] = tuple(members)

    for _ in range(n_bank_only):
        add_bank(
            start + pd.Timedelta(days=int(rng.integers(0, 120))),
            "SERVICE CHARGE - ACCOUNT MAINTENANCE",
            -_money(rng, 5.0, 45.0),
        )

    for index in range(n_ledger_only):
        add_ledger(
            start + pd.Timedelta(days=int(rng.integers(0, 120))),
            "Accrual - goods received not invoiced",
            -_money(rng, 80.0, 2500.0),
            f"ACC-{9000 + index}",
        )

    bank = pd.DataFrame(bank_rows)
    ledger = pd.DataFrame(ledger_rows)

    # Shuffle both sides so row order carries no information, and carry the
    # ground truth through the permutation.
    bank_order = rng.permutation(len(bank))
    ledger_order = rng.permutation(len(ledger))
    bank_position = {int(old): new for new, old in enumerate(bank_order)}
    ledger_position = {int(old): new for new, old in enumerate(ledger_order)}

    bank = bank.iloc[bank_order].reset_index(drop=True)
    ledger = ledger.iloc[ledger_order].reset_index(drop=True)
    shuffled_truth = {
        bank_position[old_bank]: tuple(sorted(ledger_position[r] for r in old_ledger))
        for old_bank, old_ledger in truth.items()
    }
    return SampleData(bank=bank, ledger=ledger, truth=shuffled_truth)


def write_sample_workbook(path: str = "test_reconciliation.xlsx", **kwargs) -> str:
    """Write a generated sample to an Excel workbook."""
    sample = generate_sample(**kwargs)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        sample.bank.to_excel(writer, sheet_name="Bank_Statement", index=False)
        sample.ledger.to_excel(writer, sheet_name="Internal_Ledger", index=False)
    return path
