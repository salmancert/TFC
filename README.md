# Travel Cost Forecasting

Forecasts the cost of a business trip from your own historical SAP expense
export, broken down into air ticket, accommodation, daily allowance and other
spend — with live market airfares layered on top of the route history.

Everything runs locally. No expense data leaves the machine. See
[PRIVACY.md](PRIVACY.md) for exactly what does and does not go out.

## How the estimate is built

Each component is modelled on its own terms, because they behave differently:

| Component | How it is estimated |
|---|---|
| **Air ticket** | Route history (hierarchically shrunk route → destination → global), adjusted for month and cost trend, then re-anchored to live market fares when a recent quote exists for the route. |
| **Accommodation** | Destination nightly rate × nights, with the same seasonal and trend adjustment. |
| **Daily allowance** | Policy rate × days, taken from your rates file. Exact arithmetic — never predicted. |
| **Other** | Incidental spend per day for the destination × days. |

Estimates are hierarchically shrunk: a route with plenty of history is trusted
on its own, a thin route is pulled toward its destination country average, and
an unseen route falls back to the global average. A single freak trip cannot
become a route's estimate.

Seasonality and the cost trend are fitted on *route-relative* values, so a
change in which destinations are popular is not mistaken for price inflation.

## Setup

```bash
pip install -r requirements.txt
```

Place two files in `travel_cost_forecasting/data/` (or point `TCF_DATA_DIR`
somewhere else, such as a SharePoint-synced folder):

- **`travel_data.csv`** — the SAP expense export. One row per expense line;
  lines are grouped into trips by `Report Key`. Required columns:

  `Report Key`, `Report Home Country Name`, `Report Country`,
  `Report Start Date`, `Report End Date`,
  `Report Entry Expense Type Name`, `Amount in EUR`

  Unrecognised expense types are safely counted as *other*, so the export does
  not need cleaning first.

- **`daily_allowance.xlsx`** — per-diem rates, with a `Country` column and a
  `Daily_Allowance` column. Regenerate a template with
  `python tools/make_allowance_template.py`.

## Usage

```bash
# Train on the local export, with a chronological backtest
python cli.py train --evaluate

# Forecast one trip from the command line
python cli.py forecast --home SE --dest CN --days 7 --month 4 --year 2026

# Web interface at http://127.0.0.1:5000
python app.py
```

`POST /api/forecast` returns the same result as JSON, for embedding the
estimate in another internal tool.

## Live airfare refresh

The historical model knows what the company *used to pay* on a route. A live
quote knows what the market charges *now*. The live quote is applied as a
weighted adjustment to the historical estimate, weighted by how fresh and
well-sampled it is — so it corrects the figure without letting one odd quote
replace years of booking history. Where a route has no air history at all, the
live quote leads.

Get a free key at [developers.amadeus.com](https://developers.amadeus.com):

```bash
export AMADEUS_CLIENT_ID=...
export AMADEUS_CLIENT_SECRET=...
export AMADEUS_HOSTNAME=test        # 'production' with a production key

python cli.py refresh-fares --cadence daily --dry-run   # preview, no calls
python cli.py refresh-fares --cadence daily             # fetch and cache
python cli.py fare-status                               # check freshness
```

Refreshing every route is not possible on a free tier: 77 countries is 5,852
ordered pairs against a budget of roughly 2,000 calls a month. So only routes
that actually appear in your history are refreshed, ranked by how often they
are flown — the busiest daily, the long tail rotating weekly by staleness, with
a hard call budget per run.

Schedule it with cron:

```cron
0 6 * * *  cd /path/to/TFC && python cli.py refresh-fares --cadence daily
0 3 * * 0  cd /path/to/TFC && python cli.py refresh-fares --cadence weekly
```

Fares are cached in SQLite; the web app only reads that cache. If the job never
runs or the API is unreachable, forecasts fall back to history automatically.

### Turning it off

```bash
export TCF_OFFLINE=1
```

No outbound call of any kind is then made, even with credentials set.

## Configuration

All settings live in `travel_cost_forecasting/config.py` and can be overridden
by environment variable:

| Variable | Default | Purpose |
|---|---|---|
| `TCF_DATA_DIR` | `travel_cost_forecasting/data` | Where the export and rates file live |
| `TCF_OFFLINE` | unset | Hard kill switch for all network access |
| `TCF_ALLOWANCE_BASIS` | `dest` | Whether per-diem follows destination or `home` country |
| `TCF_LEAD_DAYS` | `21,45` | Booking lead times sampled per route |
| `TCF_DAILY_TOP_N` | `10` | Routes refreshed on the daily run |
| `TCF_WEEKLY_BATCH` | `40` | Routes refreshed per weekly run |
| `TCF_CALL_BUDGET` | `150` | Hard cap on API calls per run |
| `TCF_MAX_AGE_DAYS` | `30` | Age at which a cached quote stops being used |
| `TCF_HUB_OVERRIDES` | unset | Correct the country→airport map, e.g. `US=ORD,CN=PEK` |

## Known limitations

- **Country-level routes.** The export carries only country codes, so each
  country is represented by one hub airport (`US` → `JFK`). `US → SE` cannot
  distinguish JFK from SFO. Adding a city or IATA column to the export is the
  single biggest available accuracy improvement; `resolve_airport` will use it
  automatically, and `TCF_HUB_OVERRIDES` is the interim workaround.
- **Per-diem basis.** Rates are applied by destination country by default.
  If your policy sets them by home country, set `TCF_ALLOWANCE_BASIS=home`.
- **The sandbox Amadeus tier** returns a cached subset of real fares, so
  absolute values on `AMADEUS_HOSTNAME=test` are indicative rather than exact.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

`tests/synthetic.py` generates a multi-year export with known ground truth —
route fares, seasonality and an annual trend — so the tests assert that the
model actually recovers them, rather than merely running without error.
