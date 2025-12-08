import unittest
import pandas as pd
from travel_cost_forecasting.src.data_processing import preprocess_data, ALL_COUNTRIES

class TestDataProcessing(unittest.TestCase):

    def test_preprocess_data(self):
        travel_data = pd.DataFrame({
            'Currency key': ['CNY', 'SEK', 'EUR'],
            'Currency key Name': ['Renmimbi', 'Swedish Krona', 'Euro'],
            'Report Country': ['CN', 'CN', 'ES'],
            'Report Domestic / International Flag': ['DOMESTIC', 'FOREIGN', 'DOMESTIC'],
            'Report End Date': [20230920, 20250316, 20240607],
            'Report Entry Expense Type Name': ['HOTEL', 'TAXI', 'DAILY ALLOWANCE'],
            'Report Home Country Name': ['CN', 'SE', 'ES'],
            'Report Key': ['0002535840', '0002933778', '0002781108'],
            'Report Start Date': [20230919, 20250226, 20240603],
            'Amount in EUR': [29.49, 44.16, 100.00] # Set a known actual allowance
        })
        daily_allowance_data = pd.DataFrame({
            'Country': ['CN', 'SE', 'ES'],
            'Daily_Allowance': [100, 120, 110]
        })
        preprocessed_data = preprocess_data(travel_data, daily_allowance_data)

        # Test data shape
        self.assertEqual(len(preprocessed_data), 3)
        self.assertIn('y', preprocessed_data.columns)

        # Test one-hot encoding
        self.assertIn('home_CN', preprocessed_data.columns)
        self.assertIn('dest_CN', preprocessed_data.columns)
        self.assertEqual(preprocessed_data['home_CN'].sum(), 1)
        self.assertEqual(preprocessed_data['dest_ES'].sum(), 1)

        # Test daily allowance calculation
        # Trip from ES to ES for 4 days, rate is 110. Expected = 4 * 110 = 440
        es_trip = preprocessed_data[preprocessed_data['home_ES'] == 1]
        self.assertEqual(es_trip['duration'].iloc[0], 4)
        self.assertEqual(es_trip['y_daily_allowance'].iloc[0], 440)
        # Verify the original 100 EUR is now in 'y_daily_allowance_actual'
        self.assertEqual(es_trip['y_daily_allowance_actual'].iloc[0], 100.00)

if __name__ == '__main__':
    unittest.main()
