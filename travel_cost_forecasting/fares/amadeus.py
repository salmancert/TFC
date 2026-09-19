"""Amadeus Self-Service client for live airfare lookups.

Credentials come from the environment (AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET),
never from the repository. Create a free key at developers.amadeus.com; the
'test' hostname is the free sandbox and returns a cached subset of real fares,
so absolute values there are indicative rather than exact. Point
AMADEUS_HOSTNAME at 'production' once you have a production key.

PRIVACY: the only thing sent to Amadeus is an airport pair, a date, a cabin
class and a passenger count of 1. No company, traveller or expense data.
"""
import logging
import time
from datetime import date

import requests

from .. import config
from .base import (FareProvider, FareProviderError, FareQuote, OfflineError,
                   coerce_date)

logger = logging.getLogger(__name__)

TOKEN_PATH = '/v1/security/oauth2/token'
OFFERS_PATH = '/v2/shopping/flight-offers'

#: Amadeus rejects a token a few seconds before nominal expiry under load.
TOKEN_SAFETY_MARGIN_S = 30


class AmadeusFareProvider(FareProvider):
    """Fetches the cheapest representative fare for a route and date."""

    name = 'amadeus'

    def __init__(self, client_id=None, client_secret=None, hostname=None,
                 currency=None, timeout=20, max_retries=3, session=None):
        self.client_id = client_id or config.AMADEUS_CLIENT_ID
        self.client_secret = client_secret or config.AMADEUS_CLIENT_SECRET
        self.hostname = hostname or config.AMADEUS_HOSTNAME
        self.base_url = config.AMADEUS_BASE_URLS.get(self.hostname, self.hostname)
        self.currency = currency or config.CURRENCY
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = session or requests.Session()
        self._token = None
        self._token_expires_at = 0.0
        self.calls = 0

    @property
    def configured(self):
        """True when credentials are present and offline mode is not set."""
        return bool(self.client_id and self.client_secret) and not config.OFFLINE_MODE

    # -- auth --------------------------------------------------------------
    def _access_token(self):
        if config.OFFLINE_MODE:
            raise OfflineError('Offline mode is enabled; no outbound calls allowed')
        if not (self.client_id and self.client_secret):
            raise FareProviderError(
                'AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET are not set')
        if self._token and time.time() < self._token_expires_at:
            return self._token

        response = self._session.post(
            self.base_url + TOKEN_PATH,
            data={'grant_type': 'client_credentials',
                  'client_id': self.client_id,
                  'client_secret': self.client_secret},
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=self.timeout)
        if response.status_code != 200:
            raise FareProviderError(
                'Amadeus auth failed (%s): %s' % (response.status_code, response.text[:200]))
        payload = response.json()
        self._token = payload['access_token']
        self._token_expires_at = (
            time.time() + float(payload.get('expires_in', 1799)) - TOKEN_SAFETY_MARGIN_S)
        return self._token

    # -- search ------------------------------------------------------------
    def search(self, origin, destination, departure_date, return_date=None,
               cabin='ECONOMY'):
        if config.OFFLINE_MODE:
            raise OfflineError('Offline mode is enabled; no outbound calls allowed')
        departure_date = coerce_date(departure_date)
        if return_date is not None:
            return_date = coerce_date(return_date)

        params = {
            'originLocationCode': origin,
            'destinationLocationCode': destination,
            'departureDate': departure_date.isoformat(),
            'adults': 1,
            'currencyCode': self.currency,
            'travelClass': cabin,
            'max': 20,
        }
        if return_date:
            params['returnDate'] = return_date.isoformat()

        payload = self._get(OFFERS_PATH, params)
        offers = (payload or {}).get('data') or []
        prices = []
        for offer in offers:
            try:
                total = float(offer['price']['grandTotal'])
            except (KeyError, TypeError, ValueError):
                continue
            if total > 0:
                prices.append(total)
        if not prices:
            logger.info('No Amadeus offers for %s-%s on %s',
                        origin, destination, departure_date)
            return None

        # The cheapest offer is unrepresentative of what a business traveller
        # actually books (worst timings, long layovers). The 25th percentile of
        # the returned offers tracks booked corporate fares far more closely.
        prices.sort()
        index = max(0, int(round(0.25 * (len(prices) - 1))))
        representative = prices[index]

        return FareQuote(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            price_eur=representative,
            provider=self.name,
            lead_days=(departure_date - date.today()).days,
            cabin=cabin,
            trip_type='ROUND_TRIP' if return_date else 'ONE_WAY',
        )

    def _get(self, path, params):
        """GETs a path with retry on throttling and transient server errors."""
        url = self.base_url + path
        delay = 1.0
        last_error = None
        for attempt in range(self.max_retries):
            token = self._access_token()
            self.calls += 1
            try:
                response = self._session.get(
                    url, params=params,
                    headers={'Authorization': 'Bearer ' + token},
                    timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = str(exc)
                time.sleep(delay)
                delay *= 2
                continue

            if response.status_code == 200:
                return response.json()
            if response.status_code == 401:
                # Token rejected -- drop it and let the next attempt re-auth.
                self._token, self._token_expires_at = None, 0.0
                last_error = 'unauthorised'
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last_error = 'HTTP %s' % response.status_code
                time.sleep(delay)
                delay *= 2
                continue
            if response.status_code == 400:
                # Unsupported route or malformed date: not retryable, and not
                # an error worth failing the whole refresh run over.
                logger.info('Amadeus rejected %s-%s: %s',
                            params.get('originLocationCode'),
                            params.get('destinationLocationCode'),
                            response.text[:200])
                return None
            raise FareProviderError(
                'Amadeus error %s: %s' % (response.status_code, response.text[:200]))
        raise FareProviderError('Amadeus request failed after %d attempts: %s'
                                % (self.max_retries, last_error))

    def close(self):
        self._session.close()
