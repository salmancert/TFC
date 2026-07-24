import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from scipy.sparse import hstack
import sys
import argparse
import os

def reconcile_sheets(file_path):
    # Read all sheets
    excel_file = pd.ExcelFile(file_path)
    sheet_names = excel_file.sheet_names

    if len(sheet_names) < 2:
        print(f"Error: The file {file_path} contains less than 2 sheets.")
        return

    print(f"Reading sheets: {sheet_names[0]} and {sheet_names[1]}")
    df1 = pd.read_excel(file_path, sheet_name=sheet_names[0])
    df2 = pd.read_excel(file_path, sheet_name=sheet_names[1])

    # Simple preprocessing: filling NaNs
    df1 = df1.fillna('')
    df2 = df2.fillna('')

    # Combine all columns into a single string per row for TF-IDF matching
    def combine_cols(df):
        return df.astype(str).agg(' '.join, axis=1)

    text_features1 = combine_cols(df1)
    text_features2 = combine_cols(df2)

    # Feature extraction using TF-IDF
    vectorizer = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 4))

    # Fit on both to have the same vocabulary
    vectorizer.fit(pd.concat([text_features1, text_features2]))

    X1 = vectorizer.transform(text_features1)
    X2 = vectorizer.transform(text_features2)

    # Nearest Neighbors matching
    nn = NearestNeighbors(n_neighbors=1, metric='cosine')
    nn.fit(X2)

    distances, indices = nn.kneighbors(X1)

    # Build results
    results = df1.copy()
    results['Matched_Row_Index_in_Sheet2'] = indices.flatten()
    results['Match_Distance'] = distances.flatten()
    results['Match_Confidence'] = 1 - results['Match_Distance']

    # Append the matched row data from df2
    df2_matched = df2.iloc[indices.flatten()].reset_index(drop=True)
    df2_matched.columns = [f"Matched_{col}" for col in df2_matched.columns]

    final_results = pd.concat([results.reset_index(drop=True), df2_matched], axis=1)

    # Save the results in the same file as a new sheet
    print(f"Saving results to {file_path}")
    with pd.ExcelWriter(file_path, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
        final_results.to_excel(writer, sheet_name='ML_Reconciliation_Results', index=False)

    print("Reconciliation complete. Results saved in 'ML_Reconciliation_Results' sheet.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="ML Bank Reconciliation")
    parser.add_argument("file_path", help="Path to the Excel file to reconcile")
    args = parser.parse_args()

    if os.path.exists(args.file_path):
        reconcile_sheets(args.file_path)
    else:
        print(f"File not found: {args.file_path}")
