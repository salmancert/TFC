# Invoice Reconciliation

This script reconciles invoices from two separate CSV files (`invoiced.csv` and `received.csv`) to identify discrepancies.

## How it Works

The script uses the `pandas` library to perform the following checks:

1.  **Matched Invoices:** Identifies invoices that are present in both files with the same monetary amount.
2.  **Amount Discrepancies:** Finds invoices that are in both files but have different amounts.
3.  **Missing Invoices:** Locates invoices that appear in `invoiced.csv` but are missing from `received.csv`.
4.  **Unbilled Invoices:** Finds invoices that are listed in `received.csv` but do not appear in `invoiced.csv`.

## Prerequisites

- Python 3
- pandas library

To install the required library, run the following command:
```bash
pip install pandas
```

## How to Run

1.  **Prepare your data:**
    -   Create a file named `invoiced.csv` containing the invoices that have been sent out.
    -   Create a second file named `received.csv` with the invoices that have been received and booked.
    -   Ensure both files have the following columns: `Market`, `Company Code ISP`, `Company Name`, `Company Code`, `Bill-to Party`, `Name`, and `EUR`.

2.  **Execute the script:**
    Open your terminal and run the following command in the same directory as your files:
    ```bash
    python reconcile.py
    ```

3.  **Review the output:**
    The script will print a detailed reconciliation report directly to the console, highlighting any issues found.
