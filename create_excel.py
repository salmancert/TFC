import pandas as pd
import numpy as np
import random
from datetime import datetime, timedelta
import os

# --- Create daily_allowance.xlsx ---
allowance_data = {
    'Country': ['US', 'CN', 'SE', 'BR', 'ID', 'IN', 'ES', 'IT', 'GB', 'PL', 'AE', 'AR', 'AT', 'AU', 'BA', 'BD', 'BE', 'BG', 'BH', 'BY', 'CA', 'CH', 'CL', 'CO', 'CR', 'CZ', 'DE', 'DK', 'DO', 'DZ', 'EC', 'EG', 'FI', 'FR', 'GR', 'GT', 'HR', 'HU', 'IE', 'JP', 'KE', 'KR', 'KZ', 'LK', 'LT', 'LU', 'LV', 'MA', 'MC', 'MM', 'MX', 'MY', 'NG', 'NL', 'NO', 'NZ', 'OM', 'PA', 'PE', 'PH', 'PK', 'PT', 'PY', 'RO', 'RS', 'RU', 'SA', 'SG', 'SI', 'SK', 'TH', 'TN', 'TR', 'TW', 'UY', 'VN', 'ZA'],
    'Daily_Allowance': [100, 80, 90, 70, 60, 50, 95, 95, 110, 85, 120, 75, 95, 115, 65, 40, 95, 70, 120, 60, 105, 125, 80, 70, 75, 80, 95, 110, 85, 60, 65, 55, 110, 95, 85, 70, 75, 75, 100, 120, 60, 110, 70, 50, 75, 95, 75, 65, 120, 50, 80, 70, 60, 95, 115, 115, 120, 75, 70, 60, 50, 85, 70, 70, 65, 85, 120, 120, 80, 80, 70, 60, 75, 110, 80, 60, 70]
}
df_allowance = pd.DataFrame(allowance_data)

# Ensure the data directory exists
data_dir = 'travel_cost_forecasting/data'
os.makedirs(data_dir, exist_ok=True)

allowance_filepath = os.path.join(data_dir, 'daily_allowance.xlsx')
df_allowance.to_excel(allowance_filepath, index=False)
print(f"'{allowance_filepath}' created successfully.")


# --- Create travel_data.csv ---
countries = allowance_data['Country']
expense_types = ['HOTEL', 'AIR TICKET', 'DAILY ALLOWANCE', 'TAXI', 'MEAL', 'CONFERENCE FEE', 'MISC']
num_trips = 200
travel_data_records = []

for i in range(num_trips):
    report_key = f"TRIP_{i+1:04d}"
    home_country = random.choice(countries)
    dest_country = random.choice([c for c in countries if c != home_country])

    # Generate dates with seasonality
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    year = random.choice([2022, 2023, 2024])
    start_date = datetime(year, month, day)

    duration = random.randint(2, 12)
    end_date = start_date + timedelta(days=duration)

    date_format = "%Y%m%d"
    start_date_str = start_date.strftime(date_format)
    end_date_str = end_date.strftime(date_format)

    # Generate expenses for the trip
    num_expenses = random.randint(3, 8)
    for _ in range(num_expenses):
        expense_type = random.choice(expense_types)

        # Introduce seasonality and trend to airfare and hotel
        base_airfare = 800 + (year - 2022) * 50 # Trend: prices increase over years
        seasonal_multiplier = 1.0
        if month in [6, 7, 8, 12]: # Summer and holiday season
            seasonal_multiplier = 1.4

        if expense_type == 'AIR TICKET':
            amount = random.uniform(base_airfare * 0.8, base_airfare * 1.2) * seasonal_multiplier
        elif expense_type == 'HOTEL':
            base_hotel_rate = 150 + (year - 2022) * 10
            amount = random.uniform(base_hotel_rate * 0.9, base_hotel_rate * 1.1) * duration * seasonal_multiplier
        elif expense_type == 'DAILY ALLOWANCE':
            # This is just a placeholder; it gets recalculated during preprocessing
            amount = random.uniform(40, 120) * duration
        else: # Other smaller expenses
            amount = random.uniform(20, 250)

        travel_data_records.append({
            'Report Key': report_key,
            'Report Entry Expense Type Name': expense_type,
            'Amount in EUR': round(amount, 2),
            'Report Start Date': start_date_str,
            'Report End Date': end_date_str,
            'Report Home Country Name': home_country,
            'Report Country': dest_country
        })

df_travel = pd.DataFrame(travel_data_records)

# Ensure all required columns are present
required_cols = ['Report Key', 'Report Entry Expense Type Name', 'Amount in EUR', 'Report Start Date', 'Report End Date', 'Report Home Country Name', 'Report Country']
for col in required_cols:
    if col not in df_travel.columns:
        df_travel[col] = None

df_travel = df_travel[required_cols]

travel_data_filepath = os.path.join(data_dir, 'travel_data.csv')
df_travel.to_csv(travel_data_filepath, index=False)

print(f"'{travel_data_filepath}' created successfully with {len(df_travel)} records.")
