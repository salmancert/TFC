import pandas as pd

data = {'Country': ['US', 'CN', 'SE', 'BR', 'ID', 'IN', 'ES', 'IT', 'GB', 'PL', 'AE', 'AR', 'AT', 'AU', 'BA', 'BD', 'BE', 'BG', 'BH', 'BY', 'CA', 'CH', 'CL', 'CO', 'CR', 'CZ', 'DE', 'DK', 'DO', 'DZ', 'EC', 'EG', 'FI', 'FR', 'GR', 'GT', 'HR', 'HU', 'IE', 'JP', 'KE', 'KR', 'KZ', 'LK', 'LT', 'LU', 'LV', 'MA', 'MC', 'MM', 'MX', 'MY', 'NG', 'NL', 'NO', 'NZ', 'OM', 'PA', 'PE', 'PH', 'PK', 'PT', 'PY', 'RO', 'RS', 'RU', 'SA', 'SG', 'SI', 'SK', 'TH', 'TN', 'TR', 'TW', 'UY', 'VN', 'ZA'],
        'Daily_Allowance': [100, 80, 90, 70, 60, 50, 95, 95, 110, 85, 120, 75, 95, 115, 65, 40, 95, 70, 120, 60, 105, 125, 80, 70, 75, 80, 95, 110, 85, 60, 65, 55, 110, 95, 85, 70, 75, 75, 100, 120, 60, 110, 70, 50, 75, 95, 75, 65, 120, 50, 80, 70, 60, 95, 115, 115, 120, 75, 70, 60, 50, 85, 70, 70, 65, 85, 120, 120, 80, 80, 70, 60, 75, 110, 80, 60, 70]}
df = pd.DataFrame(data)
df.to_excel('travel_cost_forecasting/data/daily_allowance.xlsx', index=False)
