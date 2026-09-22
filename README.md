# Travel Cost Forecasting

This project forecasts travel costs using a hybrid model of Prophet and LSTM. It provides a web interface for users to get cost estimates.

## Setup

1.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Place your data:**
    -   `travel_data.csv`: Your historical travel expense data.
    -   `daily_allowance_rates.xlsx`: The daily allowance rates.

    Both files should be placed in the `travel_cost_forecasting/data/` directory.

## Running the Application

1.  **Start the Flask server:**
    ```bash
    python app.py
    ```

2.  **Force retraining (optional):**
    If you have updated the data and want to force the model to retrain, use the `--retrain` flag:
    ```bash
    python app.py --retrain
    ```

3.  **Access the application:**
    Open your web browser and go to `http://127.0.0.1:5000`.

---

# Bank Reconciliation

This repository also contains a machine-learning bank reconciliation tool
that matches a bank statement against an internal ledger and writes back a
colour-coded copy of your spreadsheet.

It handles both layouts: a statement sheet and a ledger sheet to compare,
or a reconciliation pack with one sheet per bank where each sheet holds the
open ledger items and the open bank items stacked together.

```bash
pip install -r requirements-reconciliation.txt
python reconcile_gui.py                            # desktop app
python -m bank_reconciliation statement.xlsx       # command line
python -m bank_reconciliation pack.xlsx            # one sheet per bank
```

See **[RECONCILIATION.md](RECONCILIATION.md)** for the full guide.

---

# Handwriting to font

Print a template, fill it in with a pen, scan it, and get a TrueType font
made from your own handwriting — yours outright, with no licence to worry
about.

```bash
pip install -r requirements-handfont.txt
python -m handfont template -o template.pdf              # print and fill in
python -m handfont build scans/*.jpg -n "My Hand" --install
```

See **[HANDWRITING.md](HANDWRITING.md)** for the full guide.
