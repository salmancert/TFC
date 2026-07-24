import pandas as pd

def create_test_file():
    # Bank Statement Data
    bank_data = {
        'Date': ['2023-10-01', '2023-10-02', '2023-10-05', '2023-10-10'],
        'Description': ['ACH Transfer - Vendor A', 'POS Debit - Coffee Shop', 'Wire Transfer IN - Client B', 'Fee - Monthly Maintenance'],
        'Amount': [-1500.00, -4.50, 5000.00, -15.00]
    }
    df_bank = pd.DataFrame(bank_data)

    # Internal Ledger Data (slightly different descriptions/dates)
    ledger_data = {
        'Date': ['2023-10-01', '2023-10-03', '2023-10-05', '2023-10-09'],
        'Description': ['Payment to Vendor A', 'Coffee', 'Invoice 102 - Client B', 'Bank Fee'],
        'Amount': [-1500.00, -4.50, 5000.00, -15.00]
    }
    df_ledger = pd.DataFrame(ledger_data)

    with pd.ExcelWriter('test_reconciliation.xlsx', engine='openpyxl') as writer:
        df_bank.to_excel(writer, sheet_name='Bank_Statement', index=False)
        df_ledger.to_excel(writer, sheet_name='Internal_Ledger', index=False)

    print("Created test_reconciliation.xlsx")

if __name__ == '__main__':
    create_test_file()
