"""Provider-agnostic airfare interface.

Swapping fare data sources means implementing `FareProvider.search` and nothing
else. The rest of the application -- cache, refresh job, forecaster -- is
written against this interface.

PRIVACY: a fare lookup sends an origin airport, a destination airport, a date
and a cabin class. It carries no expense records, no report keys, no amounts,
no traveller identity and nothing that identifies the company. See PRIVACY.md.
"""
import abc
from dataclasses import dataclass, field
from datetime import date, datetime, timezone


def coerce_date(value):
    """Accepts a date, datetime or ISO string and returns a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip()[:10])
    raise TypeError('Unsupported date value: %r' % (value,))


class OfflineError(RuntimeError):
    """Raised when a network call is attempted while offline mode is enabled."""


class FareProviderError(RuntimeError):
    """Raised when a provider fails in a way the caller should log and skip."""


@dataclass
class FareQuote:
    """A single observed market fare for a route and departure date."""
    origin: str
    destination: str
    departure_date: date
    price_eur: float
    provider: str
    lead_days: int
    collected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))
    cabin: str = 'ECONOMY'
    trip_type: str = 'ROUND_TRIP'

    def age_days(self, now=None):
        """How stale this quote is, in days."""
        now = now or datetime.now(timezone.utc)
        collected = self.collected_at
        if collected.tzinfo is None:
            collected = collected.replace(tzinfo=timezone.utc)
        return max(0.0, (now - collected).total_seconds() / 86400.0)


class FareProvider(abc.ABC):
    """Base class for airfare sources."""

    name = 'abstract'

    @abc.abstractmethod
    def search(self, origin, destination, departure_date, return_date=None,
               cabin='ECONOMY'):
        """Returns a representative FareQuote, or None if the route is uncovered.

        Implementations must not raise for an ordinary 'no results' outcome --
        return None so the forecaster falls back to the historical model.
        """

    def close(self):
        """Releases any held resources. Override where relevant."""


class StaticFareProvider(FareProvider):
    """A provider backed by a fixed price table.

    Used for tests, for offline demonstrations, and as a way to feed the model
    negotiated corporate fares from a spreadsheet instead of a public API.
    """

    name = 'static'

    def __init__(self, prices=None, default_price=None):
        """
        Args:
            prices: {(origin, destination): price_eur} in EUR.
            default_price: Fare returned for routes absent from `prices`.
                None means the route is reported as uncovered.
        """
        self.prices = dict(prices or {})
        self.default_price = default_price
        self.calls = 0

    def search(self, origin, destination, departure_date, return_date=None,
               cabin='ECONOMY'):
        self.calls += 1
        price = self.prices.get((origin, destination), self.default_price)
        if price is None:
            return None
        departure_date = coerce_date(departure_date)
        lead = (departure_date - date.today()).days
        return FareQuote(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            price_eur=float(price),
            provider=self.name,
            lead_days=lead,
            cabin=cabin,
            trip_type='ROUND_TRIP' if return_date else 'ONE_WAY',
        )
