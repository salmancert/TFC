import pandas as pd

def reconcile_invoices(invoiced_file, received_file):
    """
    Reconciles invoices from two CSV files and identifies discrepancies.
    This version handles duplicate invoices correctly.

    Args:
        invoiced_file (str): Path to the invoiced data CSV file.
        received_file (str): Path to the received data CSV file.
    """
    try:
        invoiced_df = pd.read_csv(invoiced_file)
        received_df = pd.read_csv(received_file)
    except FileNotFoundError as e:
        print(f"Error: {e}. Please make sure the file paths are correct.")
        return

    # Normalize column names by stripping whitespace
    invoiced_df.columns = invoiced_df.columns.str.strip()
    received_df.columns = received_df.columns.str.strip()

    # Define columns that identify a unique invoice, excluding the value
    key_cols = ['Market', 'Company Code ISP', 'Company Name', 'Company Code', 'Bill-to Party', 'Name']
    all_cols = key_cols + ['EUR']

    # --- 1. Find and separate exact matches ---

    # To handle duplicates, we count occurrences of each unique row
    invoiced_counts = invoiced_df.groupby(all_cols).size().reset_index(name='invoiced_count')
    received_counts = received_df.groupby(all_cols).size().reset_index(name='received_count')

    # Merge the counts to find common invoices
    merged_counts = pd.merge(invoiced_counts, received_counts, on=all_cols, how='outer').fillna(0)

    # Calculate common counts for matched invoices
    merged_counts['matched_count'] = merged_counts.apply(lambda row: min(row['invoiced_count'], row['received_count']), axis=1)

    # Create a dataframe of matched invoices
    matched_list = []
    for _, row in merged_counts[merged_counts['matched_count'] > 0].iterrows():
        invoice_data = row[all_cols]
        for _ in range(int(row['matched_count'])):
            matched_list.append(invoice_data)

    matched_df = pd.DataFrame(matched_list, columns=all_cols) if matched_list else pd.DataFrame(columns=all_cols)

    # --- 2. Isolate unmatched invoices for further analysis ---

    merged_counts['invoiced_remainder'] = merged_counts['invoiced_count'] - merged_counts['matched_count']
    merged_counts['received_remainder'] = merged_counts['received_count'] - merged_counts['matched_count']

    invoiced_unmatched_list = []
    for _, row in merged_counts[merged_counts['invoiced_remainder'] > 0].iterrows():
        invoice_data = row[all_cols]
        for _ in range(int(row['invoiced_remainder'])):
            invoiced_unmatched_list.append(invoice_data)
    invoiced_unmatched = pd.DataFrame(invoiced_unmatched_list, columns=all_cols) if invoiced_unmatched_list else pd.DataFrame(columns=all_cols)

    received_unmatched_list = []
    for _, row in merged_counts[merged_counts['received_remainder'] > 0].iterrows():
        invoice_data = row[all_cols]
        for _ in range(int(row['received_remainder'])):
            received_unmatched_list.append(invoice_data)
    received_unmatched = pd.DataFrame(received_unmatched_list, columns=all_cols) if received_unmatched_list else pd.DataFrame(columns=all_cols)


    # --- 3. Analyze unmatched data for discrepancies, missing, and unbilled ---

    # Group by key to see amounts for potential discrepancies
    invoiced_unmatched_grouped = invoiced_unmatched.groupby(key_cols)['EUR'].apply(list).reset_index(name='invoiced_amounts') if not invoiced_unmatched.empty else pd.DataFrame(columns=key_cols + ['invoiced_amounts'])
    received_unmatched_grouped = received_unmatched.groupby(key_cols)['EUR'].apply(list).reset_index(name='received_amounts') if not received_unmatched.empty else pd.DataFrame(columns=key_cols + ['received_amounts'])

    # Merge unmatched groups to find discrepancies
    unmatched_merged = pd.merge(invoiced_unmatched_grouped, received_unmatched_grouped, on=key_cols, how='outer')

    # Discrepancies are where both amounts are present
    discrepancies_df = unmatched_merged.dropna(subset=['invoiced_amounts', 'received_amounts'])

    # Missing are where only invoiced amounts are present
    missing_invoices_df = unmatched_merged[unmatched_merged['received_amounts'].isnull()].drop(columns=['received_amounts'])

    # Unbilled are where only received amounts are present
    unbilled_invoices_df = unmatched_merged[unmatched_merged['invoiced_amounts'].isnull()].drop(columns=['invoiced_amounts'])

    # --- 4. Print Report ---
    print("--- Invoice Reconciliation Report ---")

    print("\n✅ Matched Invoices:")
    if not matched_df.empty:
        print(matched_df)
    else:
        print("No matched invoices found.")

    print("\n❌ Invoices with Amount Discrepancies:")
    if not discrepancies_df.empty:
        print(discrepancies_df)
    else:
        print("No amount discrepancies found.")

    print("\n❓ Missing Invoices (in Invoiced but not in Received):")
    if not missing_invoices_df.empty:
        print(missing_invoices_df)
    else:
        print("No missing invoices found.")

    print("\n⚠️ Unbilled Invoices (in Received but not in Invoiced):")
    if not unbilled_invoices_df.empty:
        print(unbilled_invoices_df)
    else:
        print("No unbilled invoices found.")


if __name__ == "__main__":
    reconcile_invoices('invoiced.csv', 'received.csv')
