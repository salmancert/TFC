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


# --- A harder dataset -------------------------------------------------------
# `make_export` is generated as route_base x month_factor x trend x noise, which
# is exactly the form the hierarchical estimator assumes. Benchmarking a more
# flexible model on it would be rigged in the simple model's favour.
#
# `make_complex_export` adds three kinds of structure that really do occur in
# corporate travel data and that a separable route x season x trend model cannot
# represent, no matter how much data it is given:
#
#   1. route-specific seasonality -- Brazil peaks in the southern summer while
#      China peaks in autumn, but the simple model fits ONE month curve
#   2. a Saturday-night-stay discount -- fares drop for trips of 7+ nights,
#      a non-linear interaction between duration and price
#   3. volume discounts on long stays -- nightly hotel rates fall the longer
#      you stay, so a single nightly rate per destination is wrong at both ends

#: Month factors that differ per destination, defeating a single season curve.
ROUTE_SEASONALITY = {
    'CN': {3: 1.25, 4: 1.20, 9: 1.30, 10: 1.35, 7: 0.80, 8: 0.78},
    'BR': {1: 1.30, 2: 1.35, 12: 1.25, 6: 0.80, 7: 0.75, 8: 0.80},
    'US': {5: 1.20, 6: 1.25, 9: 1.15, 1: 0.82, 2: 0.85},
    'IN': {10: 1.30, 11: 1.35, 4: 0.80, 5: 0.75},
}


def _route_season(dest, month):
    return ROUTE_SEASONALITY.get(dest, MONTH_FACTORS).get(month, 1.0)


def _stay_discount(nights):
    """Saturday-night-stay rule: a fare cliff rather than a smooth slope."""
    return 0.72 if nights >= 7 else 1.0


def _nightly_discount(nights):
    """Negotiated rates improve with length of stay, then flatten out."""
    if nights >= 14:
        return 0.70
    if nights >= 7:
        return 0.82
    if nights >= 4:
        return 0.92
    return 1.0


def make_complex_export(n_trips=900, start='2022-01-01', end='2025-12-31', seed=11):
    """Same shape of export, but with interaction structure in the costs."""
    rng = np.random.default_rng(seed)
    route_keys = list(ROUTES)
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    span_days = (end_ts - start_ts).days

    rows = []
    for i in range(n_trips):
        home, dest = route_keys[rng.integers(len(route_keys))]
        base_fare, hotel_nightly = ROUTES[(home, dest)]

        depart = start_ts + pd.Timedelta(days=int(rng.integers(span_days)))
        nights = int(np.clip(rng.gamma(2.2, 2.4), 1, 21))
        duration = nights + 1

        trend = (1.0 + ANNUAL_TREND) ** ((depart - start_ts).days / 365.25)
        season = _route_season(dest, depart.month)

        common = {
            'Currency key': 'EUR', 'Currency key Name': 'Euro',
            'Report Country': dest,
            'Report Domestic / International Flag':
                'DOMESTIC' if home == dest else 'FOREIGN',
            'Report End Date': (depart + pd.Timedelta(days=nights)).strftime('%Y%m%d'),
            'Report Home Country Name': home,
            'Report Key': '%010d' % (5000000 + i),
            'Report Start Date': depart.strftime('%Y%m%d'),
        }

        def line(expense_type, amount):
            row = dict(common)
            row['Report Entry Expense Type Name'] = expense_type
            row['Amount in EUR'] = round(float(max(0.0, amount)), 2)
            rows.append(row)

        if base_fare > 0:
            line('AIR TICKET', base_fare * trend * season
                 * _stay_discount(nights) * rng.normal(1.0, 0.15))
        line('HOTEL', hotel_nightly * nights * trend
             * _nightly_discount(nights) * rng.normal(1.0, 0.12))
        for expense_type in ('TAXI', 'MEALS', 'FUEL'):
            if rng.random() < 0.6:
                line(expense_type, OTHER_PER_DAY / 2 * duration * rng.normal(1.0, 0.3))
        line('DAILY ALLOWANCE', 85.0 * duration * rng.normal(1.0, 0.1))

    return pd.DataFrame(rows)
