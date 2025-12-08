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
    Preprocesses and aggregates travel data to create one record per trip.
    """
    # 1. Prepare and Categorize Expenses
    data = travel_data.copy()
    main_expenses = ['HOTEL', 'AIR TICKET', 'DAILY ALLOWANCE']
    data['Expense Category'] = data['Report Entry Expense Type Name'].apply(
        lambda x: x if x in main_expenses else 'Others'
    )

    # 2. Aggregate Expenses per Trip (using Report Key)
    # Pivot to sum expenses into categories for each trip
    agg_expenses = data.pivot_table(
        index='Report Key',
        columns='Expense Category',
        values='Amount in EUR',
        aggfunc='sum'
    ).fillna(0)

    # Get trip metadata (dates, countries) from the first record of each trip group
    trip_meta = data.groupby('Report Key').first()

    # Combine aggregated expenses with trip metadata
    trips = trip_meta.join(agg_expenses).reset_index()

    # 3. Refine Trip Data
    # Convert date columns and calculate duration
    trips['Report Start Date'] = pd.to_datetime(trips['Report Start Date'], format='%Y%m%d')
    trips['Report End Date'] = pd.to_datetime(trips['Report End Date'], format='%Y%m%d')
    trips['duration'] = (trips['Report End Date'] - trips['Report Start Date']).dt.days
    trips['duration'] = trips['duration'].apply(lambda x: 1 if x < 1 else x)

    # Rename columns for clarity
    trips = trips.rename(columns={
        'Report Home Country Name': 'home_country',
        'Report Country': 'dest_country',
        'Report Start Date': 'ds',
        'HOTEL': 'y_hotel',
        'AIR TICKET': 'y_air_ticket',
        'Others': 'y_others'
    })

    # 4. Calculate Official Daily Allowance
    # Merge with the daily allowance rates
    trips = pd.merge(trips, daily_allowance_data, left_on='home_country', right_on='Country', how='left')
    daily_allowance_median = trips['Daily_Allowance'].median()
    trips['Daily_Allowance'] = trips['Daily_Allowance'].fillna(daily_allowance_median)

    # Calculate the official daily allowance for the trip
    trips['y_daily_allowance'] = trips['Daily_Allowance'] * trips['duration']

    # 5. Finalize DataFrame for Modeling
    # Ensure all expense columns exist, even if they were not in the original data
    expected_cols = ['y_hotel', 'y_air_ticket', 'y_daily_allowance', 'y_others']
    for col in expected_cols:
        if col not in trips.columns:
            trips[col] = 0

    # Calculate total cost 'y'
    trips['y'] = trips['y_hotel'] + trips['y_air_ticket'] + trips['y_daily_allowance'] + trips['y_others']

    # One-hot encode country columns
    trips['home_country'] = pd.Categorical(trips['home_country'], categories=ALL_COUNTRIES)
    trips['dest_country'] = pd.Categorical(trips['dest_country'], categories=ALL_COUNTRIES)
    trips_encoded = pd.get_dummies(trips, columns=['home_country', 'dest_country'], prefix=['home', 'dest'])

    return trips_encoded
