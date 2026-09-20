"""Central configuration for the travel cost forecasting application.

Every tunable lives here so that operational settings (API credentials, refresh
cadence, call budget) can be changed without touching modelling code.
"""
import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(PACKAGE_DIR)

# TCF_DATA_DIR lets the data files live outside the repo -- for example in a
# OneDrive/SharePoint-synced folder, so the business can refresh the SAP export
# and the allowance sheet without touching the application.
DATA_DIR = os.environ.get('TCF_DATA_DIR', os.path.join(PACKAGE_DIR, 'data'))
MODELS_DIR = os.environ.get('TCF_MODELS_DIR', os.path.join(PACKAGE_DIR, 'models'))

TRAVEL_DATA_PATH = os.environ.get(
    'TCF_TRAVEL_DATA', os.path.join(DATA_DIR, 'travel_data.csv'))
DAILY_ALLOWANCE_PATH = os.environ.get(
    'TCF_ALLOWANCE_DATA', os.path.join(DATA_DIR, 'daily_allowance.xlsx'))
FARE_CACHE_PATH = os.environ.get(
    'TCF_FARE_CACHE', os.path.join(DATA_DIR, 'fare_cache.sqlite3'))
MODEL_CACHE_PATH = os.environ.get(
    'TCF_MODEL_CACHE', os.path.join(MODELS_DIR, 'forecaster.pkl'))

# --- Allowance policy -------------------------------------------------------
# Which country's per-diem rate applies. Most corporate policies set the rate by
# DESTINATION; set TCF_ALLOWANCE_BASIS=home if your policy is home-country based.
ALLOWANCE_BASIS = os.environ.get('TCF_ALLOWANCE_BASIS', 'dest')

# --- Serving ----------------------------------------------------------------
# Training on a full export takes tens of seconds and a few hundred MB. A web
# server runs several worker processes, and each one would train its own copy,
# so serving never trains by default: build the model offline with
# `python cli.py train` and the workers load it. Set TCF_TRAIN_ON_STARTUP=1
# only for single-process local use.
TRAIN_ON_STARTUP = os.environ.get(
    'TCF_TRAIN_ON_STARTUP', '').strip().lower() in ('1', 'true', 'yes', 'on')

# --- Privacy / data egress --------------------------------------------------
# OFFLINE_MODE is a hard kill switch. When set, the application makes no
# outbound network request of any kind and the airfare model runs purely on the
# local historical export. Nothing in this codebase sends expense records,
# traveller identities, report keys or amounts anywhere -- see PRIVACY.md.
# The only optional egress is an anonymous route+date fare lookup.
OFFLINE_MODE = os.environ.get('TCF_OFFLINE', '').strip().lower() in ('1', 'true', 'yes', 'on')

# --- Amadeus Self-Service API ----------------------------------------------
AMADEUS_CLIENT_ID = os.environ.get('AMADEUS_CLIENT_ID')
AMADEUS_CLIENT_SECRET = os.environ.get('AMADEUS_CLIENT_SECRET')
# 'test' is the free sandbox; switch to 'production' once you have a paid key.
AMADEUS_HOSTNAME = os.environ.get('AMADEUS_HOSTNAME', 'test')
AMADEUS_BASE_URLS = {
    'test': 'https://test.api.amadeus.com',
    'production': 'https://api.amadeus.com',
}

# --- Fare refresh policy ----------------------------------------------------
# Lead times (days before departure) sampled per route. Each entry costs one
# API call per route, so keep this list short.
FARE_LEAD_DAYS = [int(x) for x in os.environ.get('TCF_LEAD_DAYS', '21,45').split(',')]
# Routes refreshed on the daily run (the busiest ones).
FARE_DAILY_TOP_N = int(os.environ.get('TCF_DAILY_TOP_N', '10'))
# Routes refreshed per weekly run, rotating through the long tail.
FARE_WEEKLY_BATCH = int(os.environ.get('TCF_WEEKLY_BATCH', '40'))
# Hard ceiling on API calls per refresh invocation.
FARE_CALL_BUDGET = int(os.environ.get('TCF_CALL_BUDGET', '150'))
# A cached quote older than this is considered stale and stops anchoring.
FARE_MAX_AGE_DAYS = int(os.environ.get('TCF_MAX_AGE_DAYS', '30'))
# Maximum weight a live quote may take when blended with the historical model.
FARE_MAX_ANCHOR_WEIGHT = float(os.environ.get('TCF_MAX_ANCHOR_WEIGHT', '0.7'))

CURRENCY = 'EUR'
