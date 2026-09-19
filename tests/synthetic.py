"""Generates a realistic multi-year SAP-shaped export for testing.

The bundled sample export has ten rows and no air tickets at all, which is too
thin to tell a working forecaster from a broken one. This builds a dataset with
known ground truth -- route fares, destination hotel rates, seasonality and an
annual trend -- so tests can assert the model actually recovers them.
"""
import numpy as np
import pandas as pd

# route -> (base round-trip fare EUR, hotel nightly EUR at destination)
ROUTES = {
    ('SE', 'CN'): (780.0, 95.0),
    ('SE', 'US'): (640.0, 185.0),
    ('SE', 'PL'): (210.0, 78.0),
    ('DE', 'IN'): (590.0, 72.0),
    ('DE', 'GB'): (240.0, 160.0),
    ('US', 'BR'): (720.0, 110.0),
    ('IN', 'SG'): (330.0, 140.0),
    ('ES', 'ES'): (0.0, 88.0),
    ('CN', 'CN'): (0.0, 62.0),
}

#: Northern-hemisphere business travel: expensive in spring and autumn.
MONTH_FACTORS = {1: 0.88, 2: 0.95, 3: 1.10, 4: 1.15, 5: 1.12, 6: 1.02,
                 7: 0.85, 8: 0.82, 9: 1.18, 10: 1.20, 11: 1.05, 12: 0.90}

ANNUAL_TREND = 0.06          # 6% cost growth per year
OTHER_PER_DAY = 22.0         # taxis, meals, incidentals


def make_export(n_trips=900, start='2022-01-01', end='2025-12-31', seed=7):
    """Returns a DataFrame with the same column names as the real SAP export."""
    rng = np.random.default_rng(seed)
    route_keys = list(ROUTES)
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    span_days = (end_ts - start_ts).days

    rows = []
    for i in range(n_trips):
        home, dest = route_keys[rng.integers(len(route_keys))]
        base_fare, hotel_nightly = ROUTES[(home, dest)]

        depart = start_ts + pd.Timedelta(days=int(rng.integers(span_days)))
        nights = int(np.clip(rng.gamma(2.2, 2.0), 1, 21))
        duration = nights + 1

        years_elapsed = (depart - start_ts).days / 365.25
        trend = (1.0 + ANNUAL_TREND) ** years_elapsed
        season = MONTH_FACTORS[depart.month]

        report_key = '%010d' % (3000000 + i)
        common = {
            'Currency key': 'EUR', 'Currency key Name': 'Euro',
            'Report Country': dest,
            'Report Domestic / International Flag':
                'DOMESTIC' if home == dest else 'FOREIGN',
            'Report End Date': (depart + pd.Timedelta(days=nights)).strftime('%Y%m%d'),
            'Report Home Country Name': home,
            'Report Key': report_key,
            'Report Start Date': depart.strftime('%Y%m%d'),
        }

        def line(expense_type, amount):
            row = dict(common)
            row['Report Entry Expense Type Name'] = expense_type
            row['Amount in EUR'] = round(float(max(0.0, amount)), 2)
            rows.append(row)

        if base_fare > 0:
            line('AIR TICKET', base_fare * trend * season * rng.normal(1.0, 0.18))
        line('HOTEL', hotel_nightly * nights * trend * rng.normal(1.0, 0.15))
        # Incidentals arrive as several small lines, as they do in reality.
        for expense_type in ('TAXI', 'MEALS', 'FUEL'):
            if rng.random() < 0.6:
                line(expense_type, OTHER_PER_DAY / 2 * duration * rng.normal(1.0, 0.3))
        # Claimed per-diem lines exist in the export but the forecaster
        # recomputes allowance from policy, so their value is not the target.
        line('DAILY ALLOWANCE', 85.0 * duration * rng.normal(1.0, 0.1))

    return pd.DataFrame(rows)


def expected_fare(home, dest, month, year, base_year=2022):
    """Ground-truth air fare for a route, used to score the model."""
    base_fare, _ = ROUTES[(home, dest)]
    return (base_fare * MONTH_FACTORS[month]
            * (1.0 + ANNUAL_TREND) ** (year - base_year))
