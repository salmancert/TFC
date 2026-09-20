# Bank Reconciliation

Matches a bank statement against an internal ledger and gives you back a
colour-coded copy of your own spreadsheet: green where the two sides agree,
amber where a human should look, red where nothing explains the row.

There is a desktop app for everyday use and a command line for scripting.

## Install

```bash
pip install -r requirements-reconciliation.txt
```

The desktop app also needs `tkinter`, which ships with the python.org
installers on Windows and macOS. On Linux:

```bash
sudo apt install python3-tk      # Debian/Ubuntu
sudo dnf install python3-tkinter # Fedora
```

## The desktop app

```bash
python reconcile_gui.py
```

1. **Browse...** to your workbook.
2. Pick which sheet is the bank statement and which is the ledger. (Tick
   *Ledger is in a separate file* if they are not in the same workbook.)
3. Adjust the matching rules if you need to — the defaults are sensible.
4. **Reconcile.**

The result is written to `<your file>_reconciled.xlsx`, alongside the
original. **Your source file is never modified.**

### Reading the output

The output workbook holds your two sheets exactly as you supplied them, with
every row coloured and four columns appended:

| Colour | Meaning |
|---|---|
| 🟩 Green | Matched automatically |
| 🟦 Blue | Matched as a group — one bank line settling several ledger lines |
| 🟨 Amber | Likely match, confidence was below the auto-match bar — please confirm |
| 🟥 Red | Nothing on the other side explains this row |

| Column | Meaning |
|---|---|
| `Match ID` | The same ID appears on both sides of a match, so you can line them up |
| `Match Status` | `matched`, `grouped`, `review` or `unmatched` |
| `Confidence` | The score behind the decision, 0 to 1 |
| `Matched With` | The row number(s) on the other sheet |

A `Legend` sheet explains the colours and carries the run summary; a
`Matches` sheet lists every decision with both sides side by side, the
amount and date differences, and the individual feature scores.

### The interface

The window is a single scrolling column, so nothing clips on a small
laptop screen, with the **Reconcile** button pinned to the bottom where it
is always reachable.

- **Layout** is a segmented picker, set for you from what is in the file.
- **Matching rules** start collapsed, since the defaults suit most
  statements. Open them only when you want to change something.
- **Light and dark** themes; the toggle sits in the top right.

The look is built from the standard library alone - a flat restyle of ttk
plus a few hand-drawn controls in `bank_reconciliation/theme.py` - so there
is no extra dependency to install and no theme package to keep in step.

## Reconciliation packs (one sheet per bank)

This is the common case when the pack is prepared by an outsourced provider:
**one workbook, one sheet per bank account, and each sheet already laid out
as a bank reconciliation statement** — the open SAP/ledger items listed in
one block, the open bank statement items in another, everything flagged as
unmatched, waiting for someone to mark it up.

The tool handles that directly. Each sheet is matched **against itself**,
and the result is written onto a copy of your workbook with the provider's
layout, formulas and formatting left exactly as they were.

```bash
python -m bank_reconciliation pack.xlsx                  # every sheet
python -m bank_reconciliation pack.xlsx --sheets "HSBC Current"   # just one
```

In the desktop app, pick the workbook and it detects the layout for you —
you get a list of the sheets and what was found in each, and pressing
**Reconcile** marks all of them.

The layout is auto-detected; `--mode pack` or `--mode sheets` forces it.

### What it looks for

- **Section headings** such as *Unmatched items in SAP* / *Unmatched items in
  Bank Statement*. Also understood: outstanding, unidentified, unreconciled,
  open items, uncleared, unpresented, in transit; and GL, general ledger,
  cash book, books, ERP, our records for the ledger side.
- **Column headers** per block — the two blocks may have completely different
  columns (`Posting Date / Document No / Text / Amount` above,
  `Value Date / Bank Reference / Narrative / Amount` below).
- If there are no headings at all, it splits on the blank gap between the two
  lists and assumes the ledger side is listed first.

Title rows, `Balance as per ...` lines and totals are recognised and left
alone — they are never treated as items to match.

### What you get back

`<yourfile>_marked.xlsx`, containing:

- **Every original sheet, untouched except for the marking.** Item rows are
  coloured green / blue / amber / red exactly as described above, and four
  columns are appended clear of your existing data: `Match ID`,
  `Match Status`, `Confidence`, `Matched With`.
- `Matched With` gives the **spreadsheet row number** of the counterpart, in
  the same sheet — so `row 45` against a SAP item means bank item on row 45,
  and row 45 points back at it with the same `Match ID`.
- A **Reconciliation Summary** sheet at the front: the colour key, per-bank
  counts (matched / grouped / to review / still open on each side), which
  scoring model was used, and totals across every bank.

**Your source workbook is never modified** — the marked copy is a separate
file.

A sheet that does not contain two blocks (a cover sheet, an index, notes) is
reported as skipped and every other sheet still processes.

### Two things to know before you run it on a real pack

**Charts and images do not survive the round trip.** The marked copy is
written with openpyxl, which preserves cell values, formulas, styles, number
formats, column widths, merged cells and conditional formatting — but drops
embedded charts, images, pivot tables and macros. Cell content and formatting
come through intact; if your pack carries charts, keep the original (which is
never modified) as the authoritative copy.

**Formula cells are read at their last-saved value.** Items are detected from
the values Excel cached the last time the file was saved. A pack saved by
Excel always has them. A file generated by a script that never opened it in
Excel may have empty caches, in which case those rows will not be seen as
items — open and re-save it in Excel first.

## The command line

```bash
python -m bank_reconciliation statement.xlsx                    # colour-coded copy
python -m bank_reconciliation statement.xlsx -o march.xlsx      # choose the name
python -m bank_reconciliation bank.csv --ledger ledger.csv      # two separate files
python -m bank_reconciliation book.xlsx --sheets Bank Ledger    # name the sheets
python -m bank_reconciliation pack.xlsx                          # pack: each sheet vs itself
python -m bank_reconciliation book.xlsx --mode sheets           # force two-sheet mode
python -m bank_reconciliation book.xlsx --tables                # plain report tables
python -m bank_reconciliation book.xlsx --csv-dir out/          # CSVs as well
```

Useful switches: `--amount-tolerance`, `--date-window`, `--match-threshold`,
`--review-threshold`, `--sign {auto,same,flip}`, `--no-group-matching`,
`--save-model` / `--load-model`. `--help` lists them all.

## As a library

```python
from bank_reconciliation import reconcile, write_excel
from bank_reconciliation.highlight import write_highlighted_workbook

result = reconcile(bank_df, ledger_df, "Bank", "Ledger")
print(result.summary)
write_highlighted_workbook(result, "reconciled.xlsx")
```

## How the matching works

**1. It reads your columns, whatever they are called.** Dates, amounts,
descriptions and reference numbers are identified from the data rather than
from hard-coded headers. It copes with `$1,234.56`, `(1,234.56)`,
`1.234,56`, `100.00 CR`, split debit/credit columns, and `20240102`
integer dates. It works out whether `09/03/2024` means March or September
from the rest of the column — and, when a column is genuinely undecidable,
from the other table's date range.

**2. It shortlists plausible pairs** by amount, by date, and by text
similarity, rather than comparing every row against every other row.

**3. It scores each candidate pair** on ten pieces of evidence: how close
the amounts are (relative to the size of the transaction — five cents is
noise on a wire and a red flag on a coffee), whether the signs agree, how
far apart the dates are, character and word-level similarity of the
narratives, and whether an invoice or cheque number appears on both sides.

**4. It learns the weights from your file.** Reconciliation data has no
labels, so the scorer builds its own training set: pairs that agree to the
cent, within the date window, with no competing candidate on either side
become positives, and the pairs that *compete* with those become hard
negatives. A logistic regression fitted on that learns how much your
narrative and reference columns are actually worth relative to the amount
and date. Hard negatives are the important part — without them the model
would simply relearn "the amount matched".

The model is only used if it holds up: it is cross-validated, rejected if
its AUC is below 0.80, rejected if its learned weights contradict the
feature definitions, and blended with fixed accountant-style weights as a
stabiliser. If a file is too small or too ambiguous to learn anything
trustworthy, it falls back to those fixed weights instead of inventing a
model. The summary always says which was used.

**5. It picks the best overall set of pairings**, not the best partner for
each row in isolation — a Hungarian assignment over the score matrix, so
one ledger row can never be claimed by two statement rows. Pairs scoring
below the review threshold are dropped rather than forced.

**6. It then explains leftover bank lines as sums of ledger lines**, which
is how batch deposits and lump-sum supplier payments get closed.

## Accuracy

`bank_reconciliation/sample_data.py` generates both layouts — two-sheet
statement/ledger pairs, and multi-bank packs — with correct answers known, including repeated amounts, drifting dates,
differing narratives, rows that exist on only one side, and batch payments.
On ten of those, the matcher currently scores 1.000 precision and 1.000
recall, on both layouts; `tests/test_matcher.py` and `tests/test_pack.py`
assert it stays above 0.98 / 0.95.

That is synthetic data and should be read as a regression guard, not as a
claim about your bank's files. On real data, start with the defaults, look
at what lands in amber, and tune `--match-threshold` and `--date-window`
from there.

## Tests

```bash
python -m pytest tests/ -q
```

The GUI tests drive the real widgets and skip automatically when no display
is available.
