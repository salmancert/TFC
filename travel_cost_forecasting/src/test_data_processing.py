import unittest
import pandas as pd
from travel_cost_forecasting.src.data_processing import preprocess_data

class TestDataProcessing(unittest.TestCase):

    def test_preprocess_data_aggregation(self):
        # Create sample data with two expenses for the same trip (Report Key '001')
        travel_data = pd.DataFrame({
            'Report Key': ['001', '001', '002'],
            'Report Entry Expense Type Name': ['HOTEL', 'TAXI', 'AIR TICKET'],
            'Amount in EUR': [200, 50, 800],
            'Report Home Country Name': ['US', 'US', 'DE'],
            'Report Country': ['DE', 'DE', 'US'],
            'Report Start Date': [20230110, 20230110, 20230215],
            'Report End Date': [20230115, 20230115, 20230220]
        })

        daily_allowance_data = pd.DataFrame({
            'Country': ['US', 'DE'],
            'Daily_Allowance': [140, 120]
        })

        preprocessed_data = preprocess_data(travel_data, daily_allowance_data)

        # --- Assertions ---

        # 1. Should be one row per unique trip
        self.assertEqual(len(preprocessed_data), 2)

        # 2. Check the aggregated trip (Report Key '001')
        trip1 = preprocessed_data[preprocessed_data['Report Key'] == '001'].iloc[0]

        # 2a. Check aggregated costs (Hotel: 200, Others: 50)
        self.assertEqual(trip1['y_hotel'], 200)
        self.assertEqual(trip1['y_others'], 50)
        self.assertEqual(trip1['y_air_ticket'], 0) # No air ticket for this trip

        # 2b. Check duration (5 days)
        self.assertEqual(trip1['duration'], 5)

        # 2c. Check calculated daily allowance (5 days * 140/day for US)
        self.assertEqual(trip1['y_daily_allowance'], 700)

        # 2d. Check total cost (y)
        expected_total_cost_trip1 = 200 + 50 + 700
        self.assertEqual(trip1['y'], expected_total_cost_trip1)

        # 3. Check one-hot encoding
        self.assertIn('home_US', preprocessed_data.columns)
        self.assertEqual(preprocessed_data['home_US'].sum(), 1)
        self.assertEqual(preprocessed_data['dest_DE'].sum(), 1)

if __name__ == '__main__':
    unittest.main()
