"""Ingestion tests: the expense-line to trip-component transformation."""
import pandas as pd
import pytest

import synthetic
from travel_cost_forecasting import data_processing as dp


def _line(report_key, expense_type, amount, home='SE', dest='CN',
          start='20240301', end='20240305'):
    return {
        'Report Key': report_key,
        'Report Entry Expense Type Name': expense_type,
        'Amount in EUR': amount,
        'Report Home Country Name': home,
        'Report Country': dest,
        'Report Start Date': start,
        'Report End Date': end,
        'Report Domestic / International Flag': 'FOREIGN' if home != dest else 'DOMESTIC',
    }


RATES = {'CN': 80.0, 'SE': 90.0, 'PL': 85.0}


@pytest.mark.parametrize('expense_type,expected', [
    ('AIR TICKET', 'air'),
    ('Air Ticket', 'air'),
    ('AIRFARE - ECONOMY', 'air'),
    ('International Flight', 'air'),
    ('HOTEL', 'hotel'),
    ('Hotel - Lodging', 'hotel'),
    ('DAILY ALLOWANCE', 'allowance'),
    ('Per Diem Meals', 'allowance'),
    ('TAXI', 'other'),
    ('FUEL', 'other'),
    ('Something Unheard Of', 'other'),
    (None, 'other'),
])
def test_classify_expense(expense_type, expected):
    assert dp.classify_expense(expense_type) == expected


def test_lines_aggregate_into_one_trip_per_report_key():
    """Several expense lines for one trip become one row, summed per component."""
    export = pd.DataFrame([
        _line('0001', 'AIR TICKET', 600.0),
        _line('0001', 'HOTEL', 400.0),
        _line('0001', 'TAXI', 30.0),
        _line('0001', 'FUEL', 20.0),
        _line('0002', 'AIR TICKET', 250.0, dest='PL'),
    ])
    trips = dp.preprocess_data(export, allowance_rates=RATES)

    assert len(trips) == 2
    first = trips[trips['report_key'] == '0001'].iloc[0]
    assert first['air_eur'] == 600.0
    assert first['hotel_eur'] == 400.0
    assert first['other_eur'] == 50.0  # taxi + fuel combined


def test_report_key_keeps_leading_zeros(tmp_path):
    """Zero-padded SAP keys must survive the CSV round trip as text."""
    path = tmp_path / 'export.csv'
    pd.DataFrame([_line('0002535840', 'HOTEL', 100.0)]).to_csv(path, index=False)
    loaded = dp.load_travel_data(str(path))
    trips = dp.preprocess_data(loaded, allowance_rates=RATES)
    assert trips.iloc[0]['report_key'] == '0002535840'


def test_duration_is_inclusive_and_nights_is_one_fewer():
    export = pd.DataFrame([_line('0001', 'HOTEL', 100.0,
                                 start='20240301', end='20240305')])
    trips = dp.preprocess_data(export, allowance_rates=RATES)
    assert trips.iloc[0]['duration_days'] == 5   # 1st to 5th inclusive
    assert trips.iloc[0]['nights'] == 4


def test_same_day_trip_is_one_day_zero_nights():
    export = pd.DataFrame([_line('0001', 'TAXI', 20.0,
                                 start='20240301', end='20240301')])
    trips = dp.preprocess_data(export, allowance_rates=RATES)
    assert trips.iloc[0]['duration_days'] == 1
    assert trips.iloc[0]['nights'] == 0


def test_trip_dates_span_all_of_its_expense_lines():
    """Metadata is taken as min start / max end, not whichever row sorts first."""
    export = pd.DataFrame([
        _line('0001', 'HOTEL', 100.0, start='20240305', end='20240307'),
        _line('0001', 'AIR TICKET', 500.0, start='20240301', end='20240310'),
    ])
    trips = dp.preprocess_data(export, allowance_rates=RATES)
    assert trips.iloc[0]['start_date'] == pd.Timestamp('2024-03-01')
    assert trips.iloc[0]['end_date'] == pd.Timestamp('2024-03-10')


def test_allowance_is_rate_times_days_on_destination():
    export = pd.DataFrame([_line('0001', 'HOTEL', 100.0, home='SE', dest='CN',
                                 start='20240301', end='20240305')])
    trips = dp.attach_allowance(dp.build_trips(export), RATES, basis='dest')
    assert trips.iloc[0]['allowance_rate'] == 80.0       # CN, not SE
    assert trips.iloc[0]['allowance_eur'] == 80.0 * 5


def test_allowance_basis_can_follow_home_country_policy():
    export = pd.DataFrame([_line('0001', 'HOTEL', 100.0, home='SE', dest='CN',
                                 start='20240301', end='20240305')])
    trips = dp.attach_allowance(dp.build_trips(export), RATES, basis='home')
    assert trips.iloc[0]['allowance_rate'] == 90.0       # SE
    assert trips.iloc[0]['allowance_eur'] == 90.0 * 5


def test_unknown_country_falls_back_to_median_rate():
    export = pd.DataFrame([_line('0001', 'HOTEL', 100.0, home='SE', dest='PL')])
    trips = dp.attach_allowance(dp.build_trips(export), {'SE': 90.0, 'CN': 80.0})
    assert trips.iloc[0]['allowance_rate'] == 85.0       # median of 90 and 80


def test_missing_required_column_is_reported_clearly():
    export = pd.DataFrame([{'Report Key': '1', 'Amount in EUR': 10.0}])
    with pytest.raises(dp.ExportSchemaError) as excinfo:
        dp.build_trips(export)
    assert 'missing required column' in str(excinfo.value)


def test_rows_with_unparseable_dates_are_dropped_not_crashed():
    export = pd.DataFrame([
        _line('0001', 'HOTEL', 100.0),
        _line('0002', 'HOTEL', 100.0, start='not-a-date', end='also-not'),
    ])
    trips = dp.preprocess_data(export, allowance_rates=RATES)
    assert trips['report_key'].tolist() == ['0001']


def test_unknown_country_codes_are_excluded():
    export = pd.DataFrame([
        _line('0001', 'HOTEL', 100.0),
        _line('0002', 'HOTEL', 100.0, dest='ZZ'),
    ])
    trips = dp.preprocess_data(export, allowance_rates=RATES)
    assert trips['report_key'].tolist() == ['0001']


def test_realistic_export_produces_populated_components():
    trips = dp.preprocess_data(synthetic.make_export(n_trips=120),
                               allowance_rates=RATES)
    assert len(trips) == 120
    assert (trips['air_eur'] > 0).sum() > 50
    assert (trips['hotel_eur'] > 0).all()
    assert (trips['allowance_eur'] > 0).all()
