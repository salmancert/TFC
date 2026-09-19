"""Regenerates the daily allowance workbook.

The rates below are placeholders so the application runs out of the box.
Replace them with your own policy rates -- this is the file the business owns
and updates whenever the per-diem policy changes.

    python tools/make_allowance_template.py [output.xlsx]
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from travel_cost_forecasting import config          # noqa: E402
from travel_cost_forecasting.countries import ALL_COUNTRIES, COUNTRY_CODES  # noqa: E402

PLACEHOLDER_RATES = {
    'AE': 120, 'AR': 75, 'AT': 95, 'AU': 115, 'BA': 65, 'BD': 40, 'BE': 95,
    'BG': 70, 'BH': 120, 'BR': 70, 'BY': 60, 'CA': 105, 'CH': 125, 'CL': 80,
    'CN': 80, 'CO': 70, 'CR': 75, 'CZ': 80, 'DE': 95, 'DK': 110, 'DO': 85,
    'DZ': 60, 'EC': 65, 'EG': 55, 'ES': 95, 'FI': 110, 'FR': 95, 'GB': 110,
    'GR': 85, 'GT': 70, 'HR': 75, 'HU': 75, 'ID': 60, 'IE': 100, 'IN': 50,
    'IT': 95, 'JP': 120, 'KE': 60, 'KR': 110, 'KZ': 70, 'LK': 50, 'LT': 75,
    'LU': 95, 'LV': 75, 'MA': 65, 'MC': 120, 'MM': 50, 'MX': 80, 'MY': 70,
    'NG': 60, 'NL': 95, 'NO': 115, 'NZ': 115, 'OM': 120, 'PA': 75, 'PE': 70,
    'PH': 60, 'PK': 50, 'PL': 85, 'PT': 85, 'PY': 70, 'RO': 70, 'RS': 65,
    'RU': 85, 'SA': 120, 'SE': 90, 'SG': 120, 'SI': 80, 'SK': 80, 'TH': 70,
    'TN': 60, 'TR': 75, 'TW': 110, 'US': 100, 'UY': 80, 'VN': 60, 'ZA': 70,
}


def main(argv):
    output = argv[1] if len(argv) > 1 else config.DAILY_ALLOWANCE_PATH
    frame = pd.DataFrame({
        'Country': ALL_COUNTRIES,
        'Country_Name': [COUNTRY_CODES[c] for c in ALL_COUNTRIES],
        'Daily_Allowance': [PLACEHOLDER_RATES.get(c, 80) for c in ALL_COUNTRIES],
    })
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    frame.to_excel(output, index=False)
    print('Wrote %d allowance rates to %s' % (len(frame), output))
    print('These are placeholders -- replace them with your policy rates.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
