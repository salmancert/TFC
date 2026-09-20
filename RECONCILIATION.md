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

## The command line

```bash
python -m bank_reconciliation statement.xlsx                    # colour-coded copy
python -m bank_reconciliation statement.xlsx -o march.xlsx      # choose the name
python -m bank_reconciliation bank.csv --ledger ledger.csv      # two separate files
python -m bank_reconciliation book.xlsx --sheets Bank Ledger    # name the sheets
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

`bank_reconciliation/sample_data.py` generates statement/ledger pairs whose
correct answers are known, including repeated amounts, drifting dates,
differing narratives, rows that exist on only one side, and batch payments.
On ten of those, the matcher currently scores 1.000 precision and 1.000
recall, and `tests/test_matcher.py` asserts it stays above 0.98 / 0.95.

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
