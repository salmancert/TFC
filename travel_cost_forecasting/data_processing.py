"""Ingestion of the SAP expense export into a per-trip, per-component table.

The export is a flat list of expense *lines*. Forecasting needs one row per
*trip* with the cost components kept separate, because air fare, hotel and
per-diem behave completely differently: air fare is driven by route and market
prices, hotel by nights and destination, per-diem by policy arithmetic alone.

Everything here runs locally. No expense line, amount, report key or country
pair is transmitted anywhere by this module.
"""
import numpy as np
import pandas as pd

from . import config
from .countries import ALL_COUNTRIES, COUNTRY_CODES, resolve_airport  # noqa: F401

#: Canonical cost components. Anything unrecognised falls into 'other'.
COMPONENTS = ['air', 'hotel', 'allowance', 'other']

#: Substrings used to classify SAP expense type names. Matched case-insensitively
#: against the normalised expense type, longest rule first. Extend as needed --
#: a real 3-4 year export usually carries far more expense types than the
#: sample, and anything unmatched is safely counted as 'other'.
EXPENSE_RULES = [
    ('air', ('AIR TICKET', 'AIRFARE', 'AIR FARE', 'AIRLINE', 'FLIGHT', 'PLANE TICKET')),
    ('hotel', ('HOTEL', 'LODGING', 'ACCOMMODATION', 'ACCOMODATION')),
    ('allowance', ('DAILY ALLOWANCE', 'PER DIEM', 'PERDIEM', 'MEAL ALLOWANCE', 'SUBSISTENCE')),
]

COLUMN_ALIASES = {
    'report_key': ['Report Key'],
    'home_country': ['Report Home Country Name', 'Report Home Country'],
    'dest_country': ['Report Country', 'Report Destination Country'],
    'start_date': ['Report Start Date'],
    'end_date': ['Report End Date'],
    'expense_type': ['Report Entry Expense Type Name', 'Expense Type Name'],
    'amount': ['Amount in EUR', 'Approved Amount in EUR'],
    'intl_flag': ['Report Domestic / International Flag', 'Report Domestic/International Flag'],
    # Optional -- absent from the current export, used automatically if added.
    'origin_iata': ['Origin Airport Code', 'Departure Airport', 'Origin IATA'],
    'dest_iata': ['Destination Airport Code', 'Arrival Airport', 'Destination IATA'],
}

REQUIRED_FIELDS = ['report_key', 'home_country', 'dest_country',
                   'start_date', 'end_date', 'expense_type', 'amount']


class ExportSchemaError(ValueError):
    """Raised when the export is missing columns the forecaster depends on."""


def classify_expense(expense_type):
    """Maps a raw SAP expense type name onto a cost component."""
    if not isinstance(expense_type, str):
        return 'other'
    normalised = ' '.join(expense_type.upper().split())
    for component, patterns in EXPENSE_RULES:
        for pattern in patterns:
            if pattern in normalised:
                return component
    return 'other'


def _resolve_columns(frame):
    """Maps the export's real column names onto our canonical field names."""
    lookup = {str(c).strip().lower(): c for c in frame.columns}
    resolved = {}
    for field, candidates in COLUMN_ALIASES.items():
        for candidate in candidates:
            actual = lookup.get(candidate.strip().lower())
            if actual is not None:
                resolved[field] = actual
                break
    missing = [f for f in REQUIRED_FIELDS if f not in resolved]
    if missing:
        raise ExportSchemaError(
            'SAP export is missing required column(s): %s. Found: %s'
            % (', '.join(missing), ', '.join(map(str, frame.columns))))
    return resolved


def load_travel_data(filepath=None):
    """Loads the SAP expense export from CSV or Excel."""
    filepath = filepath or config.TRAVEL_DATA_PATH
    # Everything is read as text so identifiers keep their exact form -- report
    # keys are zero-padded and must not be silently turned into integers.
    # Amounts and dates are coerced explicitly further down the pipeline.
    if str(filepath).lower().endswith(('.xlsx', '.xls', '.xlsm')):
        return pd.read_excel(filepath, engine='openpyxl', dtype=str)
    return pd.read_csv(filepath, dtype=str)


def load_daily_allowance(filepath=None):
    """Loads per-diem rates into a {country_code: rate} mapping.

    This is the file you refresh whenever the allowance policy changes; it is
    applied as exact arithmetic, never modelled.
    """
    filepath = filepath or config.DAILY_ALLOWANCE_PATH
    if str(filepath).lower().endswith('.csv'):
        rates = pd.read_csv(filepath)
    else:
        rates = pd.read_excel(filepath, engine='openpyxl')

    lookup = {str(c).strip().lower(): c for c in rates.columns}
    country_col = lookup.get('country') or lookup.get('country code')
    rate_col = (lookup.get('daily_allowance') or lookup.get('daily allowance')
                or lookup.get('rate') or lookup.get('amount'))
    if country_col is None or rate_col is None:
        raise ExportSchemaError(
            'Allowance file needs a country column and a rate column; found: %s'
            % ', '.join(map(str, rates.columns)))

    rates = rates[[country_col, rate_col]].dropna()
    rates[country_col] = rates[country_col].astype(str).str.strip().str.upper()
    rates[rate_col] = pd.to_numeric(rates[rate_col], errors='coerce')
    rates = rates.dropna()
    return dict(zip(rates[country_col], rates[rate_col].astype(float)))


def _parse_dates(series):
    """Parses SAP's YYYYMMDD dates, tolerating already-parsed values."""
    text = series.astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
    parsed = pd.to_datetime(text, format='%Y%m%d', errors='coerce')
    if parsed.isna().any():
        fallback = pd.to_datetime(series, errors='coerce')
        parsed = parsed.fillna(fallback)
    return parsed


def build_trips(travel_data):
    """Aggregates expense lines into one row per trip with separate components.

    Returns:
        A DataFrame with one row per Report Key carrying `air_eur`, `hotel_eur`,
        `allowance_eur_actual` and `other_eur`, plus trip metadata.
    """
    cols = _resolve_columns(travel_data)
    data = travel_data.rename(columns={v: k for k, v in cols.items()}).copy()

    data['amount'] = pd.to_numeric(data['amount'], errors='coerce').fillna(0.0)
    data['start_date'] = _parse_dates(data['start_date'])
    data['end_date'] = _parse_dates(data['end_date'])
    data['report_key'] = data['report_key'].astype(str).str.strip()
    for field in ('home_country', 'dest_country'):
        data[field] = data[field].astype(str).str.strip().str.upper()
    data['component'] = data['expense_type'].map(classify_expense)

    # Sum each component per trip. Expense lines within a trip are additive.
    sums = (data.pivot_table(index='report_key', columns='component',
                             values='amount', aggfunc='sum')
            .reindex(columns=COMPONENTS, fill_value=0.0)
            .fillna(0.0))
    sums.columns = ['%s_eur' % c for c in sums.columns]

    agg_spec = {
        'home_country': ('home_country', 'first'),
        'dest_country': ('dest_country', 'first'),
        # Trips can span several expense lines with differing dates; take the
        # widest window rather than whichever row happened to sort first.
        'start_date': ('start_date', 'min'),
        'end_date': ('end_date', 'max'),
        'n_lines': ('amount', 'size'),
    }
    for optional in ('intl_flag', 'origin_iata', 'dest_iata'):
        if optional in data.columns:
            agg_spec[optional] = (optional, 'first')

    meta = data.groupby('report_key').agg(**agg_spec)
    trips = meta.join(sums).reset_index()

    trips = trips.dropna(subset=['start_date', 'end_date'])
    trips = trips[trips['home_country'].isin(ALL_COUNTRIES)
                  & trips['dest_country'].isin(ALL_COUNTRIES)]

    # Duration: SAP start/end are inclusive calendar dates, so a same-day trip
    # is 1 day. Hotel nights are one fewer than allowance days.
    span = (trips['end_date'] - trips['start_date']).dt.days
    trips['duration_days'] = span.clip(lower=0).astype(int) + 1
    trips['nights'] = (trips['duration_days'] - 1).clip(lower=0)

    trips['month'] = trips['start_date'].dt.month
    trips['year'] = trips['start_date'].dt.year
    # Continuous time index in years, used to fit the cost trend.
    trips['t_years'] = (trips['start_date'] - pd.Timestamp('2000-01-01')).dt.days / 365.25
    trips['route'] = trips['home_country'] + '-' + trips['dest_country']
    trips['is_international'] = trips['home_country'] != trips['dest_country']

    trips['rendered_air'] = trips['air_eur'] > 0
    trips['rendered_hotel'] = trips['hotel_eur'] > 0

    return trips.sort_values('start_date').reset_index(drop=True)


def attach_allowance(trips, allowance_rates, basis=None):
    """Adds the policy per-diem as exact arithmetic: rate x days.

    The rate is keyed on destination by default, which is the common corporate
    policy. Set TCF_ALLOWANCE_BASIS=home if your policy is home-country based.
    """
    basis = basis or config.ALLOWANCE_BASIS
    key_col = 'home_country' if basis == 'home' else 'dest_country'
    trips = trips.copy()

    # The fallback depends on the rates file, not on whether any trip in this
    # particular batch happened to match one -- otherwise a batch travelling
    # exclusively to unmapped countries would silently get a zero allowance.
    rate = trips[key_col].map(allowance_rates)
    fallback = float(np.median(list(allowance_rates.values()))) if allowance_rates else 0.0
    rate = rate.fillna(fallback)

    trips['allowance_rate'] = rate.astype(float)
    trips['allowance_basis_country'] = trips[key_col]
    trips['allowance_eur'] = trips['allowance_rate'] * trips['duration_days']
    return trips


def preprocess_data(travel_data, daily_allowance_data=None, allowance_rates=None):
    """Full local pipeline: expense lines -> modelling-ready trip table."""
    if allowance_rates is None:
        if daily_allowance_data is None:
            raise ValueError('Provide either allowance_rates or daily_allowance_data')
        if isinstance(daily_allowance_data, dict):
            allowance_rates = daily_allowance_data
        else:
            frame = daily_allowance_data
            lookup = {str(c).strip().lower(): c for c in frame.columns}
            country_col = lookup.get('country')
            rate_col = lookup.get('daily_allowance') or lookup.get('daily allowance')
            allowance_rates = dict(zip(
                frame[country_col].astype(str).str.strip().str.upper(),
                pd.to_numeric(frame[rate_col], errors='coerce').astype(float)))

    trips = build_trips(travel_data)
    trips = attach_allowance(trips, allowance_rates)
    # Total actually incurred, using the policy allowance rather than the
    # claimed one so the target matches what the forecaster will reproduce.
    trips['total_eur'] = (trips['air_eur'] + trips['hotel_eur']
                          + trips['allowance_eur'] + trips['other_eur'])
    return trips
