"""Local SQLite store for collected fare quotes.

The cache is what makes the refresh cadence decoupled from request handling: a
scheduled job writes quotes, the web app only ever reads them. If the job never
runs, or the API is unreachable, reads simply return nothing and the forecaster
falls back to its historical model.

The database holds market fares for anonymous airport pairs. It contains no
expense data and no personal data.
"""
import os
import sqlite3
from datetime import date, datetime, timezone

from .base import FareQuote

SCHEMA = """
CREATE TABLE IF NOT EXISTS fare_quotes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    origin          TEXT NOT NULL,
    destination     TEXT NOT NULL,
    departure_date  TEXT NOT NULL,
    lead_days       INTEGER NOT NULL,
    price_eur       REAL NOT NULL,
    provider        TEXT NOT NULL,
    cabin           TEXT NOT NULL DEFAULT 'ECONOMY',
    trip_type       TEXT NOT NULL DEFAULT 'ROUND_TRIP',
    collected_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quotes_route
    ON fare_quotes (origin, destination, collected_at);

CREATE TABLE IF NOT EXISTS refresh_log (
    origin        TEXT NOT NULL,
    destination   TEXT NOT NULL,
    last_attempt  TEXT,
    last_success  TEXT,
    last_status   TEXT,
    PRIMARY KEY (origin, destination)
);
"""


def _iso(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _parse_dt(text):
    if not text:
        return None
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class FareCache:
    """SQLite-backed store of fare quotes."""

    def __init__(self, path):
        self.path = path
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=15.0)
        self._conn.row_factory = sqlite3.Row
        # The refresh job writes while web workers read. Write-ahead logging
        # lets readers carry on during a write instead of hitting "database is
        # locked", and the busy timeout absorbs the brief exclusive moments.
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('PRAGMA busy_timeout=15000')
        self._conn.execute('PRAGMA synchronous=NORMAL')
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # -- writes ------------------------------------------------------------
    def put(self, quote):
        """Stores one quote. Quotes are append-only so trends stay visible."""
        self._conn.execute(
            'INSERT INTO fare_quotes (origin, destination, departure_date,'
            ' lead_days, price_eur, provider, cabin, trip_type, collected_at)'
            ' VALUES (?,?,?,?,?,?,?,?,?)',
            (quote.origin, quote.destination, str(quote.departure_date),
             int(quote.lead_days), float(quote.price_eur), quote.provider,
             quote.cabin, quote.trip_type, _iso(quote.collected_at)))
        self._conn.commit()

    def log_attempt(self, origin, destination, status, succeeded):
        """Records a refresh attempt so the rotation can skip fresh routes."""
        now = _iso(datetime.now(timezone.utc))
        self._conn.execute(
            'INSERT INTO refresh_log (origin, destination, last_attempt,'
            ' last_success, last_status) VALUES (?,?,?,?,?)'
            ' ON CONFLICT(origin, destination) DO UPDATE SET'
            ' last_attempt=excluded.last_attempt, last_status=excluded.last_status,'
            ' last_success=COALESCE(excluded.last_success, refresh_log.last_success)',
            (origin, destination, now, now if succeeded else None, status))
        self._conn.commit()

    # -- reads -------------------------------------------------------------
    def recent_quotes(self, origin, destination, max_age_days=30, now=None):
        """Returns quotes for a route collected within `max_age_days`."""
        rows = self._conn.execute(
            'SELECT * FROM fare_quotes WHERE origin=? AND destination=?'
            ' ORDER BY collected_at DESC LIMIT 200',
            (origin, destination)).fetchall()
        now = now or datetime.now(timezone.utc)
        quotes = []
        for row in rows:
            collected = _parse_dt(row['collected_at'])
            if (now - collected).total_seconds() / 86400.0 > max_age_days:
                continue
            quotes.append(FareQuote(
                origin=row['origin'], destination=row['destination'],
                departure_date=date.fromisoformat(row['departure_date']),
                price_eur=row['price_eur'], provider=row['provider'],
                lead_days=row['lead_days'], collected_at=collected,
                cabin=row['cabin'], trip_type=row['trip_type']))
        return quotes

    def market_price(self, origin, destination, max_age_days=30, now=None):
        """A single representative current fare for the route.

        Uses the median across recent quotes so one unusual lead time or a
        single cheap seat cannot swing the anchor.

        Returns:
            (price_eur, n_quotes, age_days) or (None, 0, None) when uncovered.
        """
        quotes = self.recent_quotes(origin, destination, max_age_days, now)
        if not quotes:
            return None, 0, None
        prices = sorted(q.price_eur for q in quotes)
        mid = len(prices) // 2
        median = (prices[mid] if len(prices) % 2
                  else (prices[mid - 1] + prices[mid]) / 2.0)
        freshest = min(q.age_days(now) for q in quotes)
        return median, len(quotes), freshest

    def last_attempt(self, origin, destination):
        row = self._conn.execute(
            'SELECT last_attempt FROM refresh_log WHERE origin=? AND destination=?',
            (origin, destination)).fetchone()
        return _parse_dt(row['last_attempt']) if row else None

    def stats(self):
        """Summary used by the UI to show how fresh the fare data is."""
        row = self._conn.execute(
            'SELECT COUNT(*) AS n, COUNT(DISTINCT origin || destination) AS routes,'
            ' MAX(collected_at) AS newest FROM fare_quotes').fetchone()
        return {
            'quotes': row['n'] or 0,
            'routes': row['routes'] or 0,
            'last_refresh': _parse_dt(row['newest']),
        }

    def close(self):
        self._conn.close()
