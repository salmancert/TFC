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

## Which model is used

Each component is fitted two ways and the better one is kept:

- **Hierarchical estimator** — route level × season × trend. Separable,
  explainable, works on small data.
- **Gradient boosted trees** (`HistGradientBoostingRegressor`) — can learn
  interactions the hierarchical model cannot express, such as a nightly rate
  that falls on long stays, a destination whose peak season differs from
  everywhere else, or a fare cliff at a Saturday-night stay.

The choice is made per component by rolling-origin cross-validation on the
*training* data only — three chronological folds, each training before a cut
and testing after it. The tree is adopted only if it wins a majority of folds
by a clear margin and does not make absolute error materially worse. A single
split was not enough: on data that genuinely suits the simple model, a tree
still won one split by chance, which is exactly the trap this avoids.

Below 150 observations for a component, no tree is attempted. Trees also cannot
extrapolate beyond their training period, so the annual trend is divided out
before fitting and re-applied analytically at prediction time — otherwise a
forecast for 2027 would come back at today's prices.

Per-diem is never handed to either model. It is policy arithmetic.

`python cli.py train --evaluate` prints which estimator won each component and
why. Components using a tree are marked **boosted** in the web interface.

### Measured effect

Benchmarked on synthetic exports with known ground truth (`tests/synthetic.py`),
comparing hierarchical-only against automatic selection, on the trip total:

| Dataset | MdAPE hierarchical | MdAPE auto-selected | Change |
|---|---|---|---|
| Separable costs, 900 trips | 8.0% | 8.0% | no change — tree correctly declined |
| Interaction structure, 900 trips | 11.9% | 8.4% | **−30%** |
| Interaction structure, 2,500 trips | 10.4% | 7.3% | **−30%** |
| Interaction structure, 160 trips | 6.8% | 6.8% | no change — below threshold |

The gain depends entirely on whether such structure exists in your data. Where
it does not, selection falls back to the simpler model and changes nothing —
which is the point: the upside is captured without risking a regression.

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

> Running it for a team? See **[DEPLOYMENT.md](DEPLOYMENT.md)** — the steps
> below are the single-user path. Serving to other people has one extra rule:
> build the model offline first, because a web server runs several worker
> processes and none of them should be training.

```bash
# Train on the local export, with a chronological backtest
python cli.py train --evaluate

# Forecast one trip from the command line
python cli.py forecast --home SE --dest CN --days 7 --month 4 --year 2026

# Web interface at http://127.0.0.1:5000
python app.py
```

`POST /api/forecast` returns the same result as JSON, for embedding the
estimate in another internal tool. `GET /healthz` reports model and fare
freshness for monitoring.

### Serving it to a team

```bash
python cli.py train                                    # build the model first
gunicorn --workers 3 --preload --bind 0.0.0.0:8000 wsgi:application
```

Or `docker compose --profile tools run --rm train && docker compose up -d`.
On Windows use `waitress-serve --listen=0.0.0.0:8000 wsgi:application`.
Full instructions, service units and scheduled jobs: **[DEPLOYMENT.md](DEPLOYMENT.md)**.

The app has no authentication by design — it is meant to sit on an internal
interface. Put a reverse proxy with SSO in front if that changes.

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

## Performance

Measured on a 151,000-line export (33,000 trips), which is roughly four years
of a mid-sized travel programme:

| | |
|---|---|
| Load and preprocess | 0.7s |
| Train, both estimators with cross-validated selection | 28s, 284 MB peak |
| Forecast latency | 15 ms |
| Serving, 3 workers with `--preload` | ~560 MB total |
| Backtest | ~2 minutes |

Training is the only heavy step and runs monthly. Serving is cheap.

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
- **Incidental spend ("other") is inherently noisy** — roughly 30% MdAPE in
  every benchmark, under either estimator. It is a small share of trip cost, so
  this matters little for the total, but do not read that line as precise.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

`tests/synthetic.py` generates multi-year exports with known ground truth, so
the tests assert that the model actually recovers them rather than merely
running without error. It provides two generators on purpose:

- `make_export` — costs are separable (route × season × trend), matching the
  hierarchical model's assumptions
- `make_complex_export` — adds route-specific seasonality, stay discounts and
  volume discounts, which a separable model structurally cannot represent

Benchmarking only on the first would be rigged in the simple model's favour.
The selection tests assert both directions: the tree must be adopted when
structure exists, and declined when it does not.
