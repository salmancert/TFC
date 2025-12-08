import pandas as pd

ALL_COUNTRIES = [
    'AE', 'AR', 'AT', 'AU', 'BA', 'BD', 'BE', 'BG', 'BH', 'BR', 'BY',
    'CA', 'CH', 'CL', 'CN', 'CO', 'CR', 'CZ', 'DE', 'DK', 'DO', 'DZ',
    'EC', 'EG', 'ES', 'FI', 'FR', 'GB', 'GR', 'GT', 'HR', 'HU', 'ID',
    'IE', 'IN', 'IT', 'JP', 'KE', 'KR', 'KZ', 'LK', 'LT', 'LU', 'LV',
    'MA', 'MC', 'MM', 'MX', 'MY', 'NG', 'NL', 'NO', 'NZ', 'OM', 'PA',
    'PE', 'PH', 'PK', 'PL', 'PT', 'PY', 'RO', 'RS', 'RU', 'SA', 'SE',
    'SG', 'SI', 'SK', 'TH', 'TN', 'TR', 'TW', 'US', 'UY', 'VN', 'ZA'
]

def load_travel_data(filepath):
    """
    Loads travel data from a CSV file.
    """
    return pd.read_csv(filepath)

def load_daily_allowance(filepath):
    """
    Loads daily allowance data from an Excel file.
    """
    return pd.read_excel(filepath)

def preprocess_data(travel_data, daily_allowance_data):
    """
    Preprocesses the travel and daily allowance data.
    """
    # Merge travel data with daily allowance data
    data = pd.merge(travel_data, daily_allowance_data, left_on='Report Home Country Name', right_on='Country', how='left')

    # Fill missing daily allowance rates with the median
    daily_allowance_median = data['Daily_Allowance'].median()
    data['Daily_Allowance'] = data['Daily_Allowance'].fillna(daily_allowance_median)

    # Convert date columns to datetime objects
    data['Report Start Date'] = pd.to_datetime(data['Report Start Date'], format='%Y%m%d')
    data['Report End Date'] = pd.to_datetime(data['Report End Date'], format='%Y%m%d')

    # Calculate trip duration
    data['duration'] = (data['Report End Date'] - data['Report Start Date']).dt.days
    # Ensure duration is at least 1 day
    data['duration'] = data['duration'].apply(lambda x: 1 if x < 1 else x)

    # Set 'ds' column for Prophet
    data['ds'] = data['Report Start Date']

    # Group expense types
    main_expenses = ['HOTEL', 'AIR TICKET', 'DAILY ALLOWANCE']
    data['Expense Category'] = data['Report Entry Expense Type Name'].apply(lambda x: x if x in main_expenses else 'Others')

    # Pivot the data, keeping Daily_Allowance rate
    data_pivot = data.pivot_table(index=['ds', 'Report Home Country Name', 'Report Country', 'duration', 'Daily_Allowance'],
                                  columns='Expense Category',
                                  values='Amount in EUR',
                                  aggfunc='sum').reset_index()

    # Rename columns and fill NaN values for expense types
    data_pivot = data_pivot.rename(columns={'Report Home Country Name': 'home_country', 'Report Country': 'dest_country'})
    data_pivot = data_pivot.rename(columns={'HOTEL': 'y_hotel', 'AIR TICKET': 'y_air_ticket', 'DAILY ALLOWANCE': 'y_daily_allowance_actual', 'Others': 'y_others'})

    # Ensure all expense columns exist
    expected_cols = ['y_hotel', 'y_air_ticket', 'y_daily_allowance_actual', 'y_others']
    for col in expected_cols:
        if col not in data_pivot.columns:
            data_pivot[col] = 0

    data_pivot = data_pivot.fillna(0)

    # Replace actual daily allowance with calculated one based on official rate
    data_pivot['y_daily_allowance'] = data_pivot['Daily_Allowance'] * data_pivot['duration']

    # Calculate total cost 'y'
    data_pivot['y'] = data_pivot['y_hotel'] + data_pivot['y_air_ticket'] + data_pivot['y_daily_allowance'] + data_pivot['y_others']

    # One-hot encode country columns
    data_pivot['home_country'] = pd.Categorical(data_pivot['home_country'], categories=ALL_COUNTRIES)
    data_pivot['dest_country'] = pd.Categorical(data_pivot['dest_country'], categories=ALL_COUNTRIES)

    data_pivot = pd.get_dummies(data_pivot, columns=['home_country', 'dest_country'], prefix=['home', 'dest'])

    return data_pivot
