"""Country reference data and the country -> representative hub airport map.

The SAP export only carries country codes, so a fare lookup has to pick one
airport to stand in for each country. That is an accuracy ceiling: for large
countries a single hub cannot represent every route (US -> JFK ignores SFO,
ORD and DFW entirely). If the export is ever extended with city or IATA
columns, `resolve_airport` will prefer them automatically.

`HUB_OVERRIDES` exists so the mapping can be corrected operationally without a
code change -- set TCF_HUB_OVERRIDES="US=ORD,CN=PEK" in the environment.
"""
import os

COUNTRY_CODES = {
    'AE': 'United Arab Emirates', 'AR': 'Argentina', 'AT': 'Austria', 'AU': 'Australia',
    'BA': 'Bosnia and Herzegovina', 'BD': 'Bangladesh', 'BE': 'Belgium', 'BG': 'Bulgaria',
    'BH': 'Bahrain', 'BR': 'Brazil', 'BY': 'Belarus', 'CA': 'Canada', 'CH': 'Switzerland',
    'CL': 'Chile', 'CN': 'China', 'CO': 'Colombia', 'CR': 'Costa Rica', 'CZ': 'Czech Republic',
    'DE': 'Germany', 'DK': 'Denmark', 'DO': 'Dominican Republic', 'DZ': 'Algeria',
    'EC': 'Ecuador', 'EG': 'Egypt', 'ES': 'Spain', 'FI': 'Finland', 'FR': 'France',
    'GB': 'United Kingdom', 'GR': 'Greece', 'GT': 'Guatemala', 'HR': 'Croatia', 'HU': 'Hungary',
    'ID': 'Indonesia', 'IE': 'Ireland', 'IN': 'India', 'IT': 'Italy', 'JP': 'Japan',
    'KE': 'Kenya', 'KR': 'South Korea', 'KZ': 'Kazakhstan', 'LK': 'Sri Lanka',
    'LT': 'Lithuania', 'LU': 'Luxembourg', 'LV': 'Latvia', 'MA': 'Morocco', 'MC': 'Monaco',
    'MM': 'Myanmar', 'MX': 'Mexico', 'MY': 'Malaysia', 'NG': 'Nigeria', 'NL': 'Netherlands',
    'NO': 'Norway', 'NZ': 'New Zealand', 'OM': 'Oman', 'PA': 'Panama', 'PE': 'Peru',
    'PH': 'Philippines', 'PK': 'Pakistan', 'PL': 'Poland', 'PT': 'Portugal', 'PY': 'Paraguay',
    'RO': 'Romania', 'RS': 'Serbia', 'RU': 'Russia', 'SA': 'Saudi Arabia', 'SE': 'Sweden',
    'SG': 'Singapore', 'SI': 'Slovenia', 'SK': 'Slovakia', 'TH': 'Thailand', 'TN': 'Tunisia',
    'TR': 'Turkey', 'TW': 'Taiwan', 'US': 'United States', 'UY': 'Uruguay', 'VN': 'Vietnam',
    'ZA': 'South Africa',
}

ALL_COUNTRIES = sorted(COUNTRY_CODES.keys())

#: Primary international gateway per country, used when no city is available.
COUNTRY_HUBS = {
    'AE': 'DXB', 'AR': 'EZE', 'AT': 'VIE', 'AU': 'SYD', 'BA': 'SJJ', 'BD': 'DAC',
    'BE': 'BRU', 'BG': 'SOF', 'BH': 'BAH', 'BR': 'GRU', 'BY': 'MSQ', 'CA': 'YYZ',
    'CH': 'ZRH', 'CL': 'SCL', 'CN': 'PVG', 'CO': 'BOG', 'CR': 'SJO', 'CZ': 'PRG',
    'DE': 'FRA', 'DK': 'CPH', 'DO': 'SDQ', 'DZ': 'ALG', 'EC': 'UIO', 'EG': 'CAI',
    'ES': 'MAD', 'FI': 'HEL', 'FR': 'CDG', 'GB': 'LHR', 'GR': 'ATH', 'GT': 'GUA',
    'HR': 'ZAG', 'HU': 'BUD', 'ID': 'CGK', 'IE': 'DUB', 'IN': 'DEL', 'IT': 'FCO',
    'JP': 'HND', 'KE': 'NBO', 'KR': 'ICN', 'KZ': 'ALA', 'LK': 'CMB', 'LT': 'VNO',
    'LU': 'LUX', 'LV': 'RIX', 'MA': 'CMN', 'MC': 'NCE', 'MM': 'RGN', 'MX': 'MEX',
    'MY': 'KUL', 'NG': 'LOS', 'NL': 'AMS', 'NO': 'OSL', 'NZ': 'AKL', 'OM': 'MCT',
    'PA': 'PTY', 'PE': 'LIM', 'PH': 'MNL', 'PK': 'KHI', 'PL': 'WAW', 'PT': 'LIS',
    'PY': 'ASU', 'RO': 'OTP', 'RS': 'BEG', 'RU': 'SVO', 'SA': 'RUH', 'SE': 'ARN',
    'SG': 'SIN', 'SI': 'LJU', 'SK': 'BTS', 'TH': 'BKK', 'TN': 'TUN', 'TR': 'IST',
    'TW': 'TPE', 'US': 'JFK', 'UY': 'MVD', 'VN': 'SGN', 'ZA': 'JNB',
}


def _load_overrides():
    """Parses TCF_HUB_OVERRIDES, e.g. "US=ORD,CN=PEK"."""
    raw = os.environ.get('TCF_HUB_OVERRIDES', '')
    overrides = {}
    for pair in raw.split(','):
        if '=' not in pair:
            continue
        country, _, iata = pair.partition('=')
        country, iata = country.strip().upper(), iata.strip().upper()
        if len(country) == 2 and len(iata) == 3:
            overrides[country] = iata
    return overrides


HUB_OVERRIDES = _load_overrides()


def resolve_airport(country_code, iata=None):
    """Returns the IATA code to use for a country.

    Args:
        country_code: Two-letter country code from the SAP export.
        iata: An explicit airport code, when the export provides one. Takes
            precedence over the country hub.

    Returns:
        A three-letter IATA code, or None if the country is unknown.
    """
    if iata:
        iata = str(iata).strip().upper()
        if len(iata) == 3 and iata.isalpha():
            return iata
    if not country_code:
        return None
    country_code = str(country_code).strip().upper()
    return HUB_OVERRIDES.get(country_code) or COUNTRY_HUBS.get(country_code)


def country_name(country_code):
    """Human-readable country name, falling back to the raw code."""
    return COUNTRY_CODES.get(country_code, country_code)
