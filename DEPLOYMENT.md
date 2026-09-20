# Deploying to an internal server

This sets the forecaster up as an internal web service: one machine runs it,
everyone uses a browser, and the expense export lives in exactly one controlled
place. See [PRIVACY.md](PRIVACY.md) for what does and does not leave that host.

There is **no authentication** in the application. It is designed to sit on an
internal interface, reachable from your network and nowhere else. If that
assumption stops holding, put a reverse proxy with SSO in front of it — nothing
in the app needs to change.

## What you need

- A Linux VM or a Windows server on the internal network, 2 vCPU / 2 GB RAM
- Python 3.10+ (or Docker)
- Roughly 1 GB of disk for the app, the export and the fare cache

Measured on a 151,000-line export (33,000 trips):

| | |
|---|---|
| Training | 28s, 284 MB peak |
| Model file | ~5 MB |
| Serving | 3 workers, ~560 MB total with `--preload` |
| Forecast latency | 15 ms |
| Backtest (`--evaluate`) | ~2 minutes |

The machine does no heavy work while serving. Sizing is driven by training,
which happens once a month.

## The one rule

**Train offline. Never in a web worker.**

Training takes ~30s and a few hundred MB, and a web server runs several worker
processes — each would train its own copy on every restart. So `wsgi.py`
refuses to train and tells you to build the model first:

```bash
python cli.py train --evaluate     # writes forecaster.pkl
```

Only then start the server. `python app.py` (the development path) still trains
on demand, because it is a single process.

## Option A — Docker (simplest)

```bash
git clone <your-internal-mirror>/TFC.git /opt/tcf && cd /opt/tcf
mkdir -p data models

# Put travel_data.csv and daily_allowance.xlsx in ./data
cp /path/to/sap_export.csv        data/travel_data.csv
cp /path/to/allowance_rates.xlsx  data/daily_allowance.xlsx

# Optional: live fares
cat > .env <<'ENV'
AMADEUS_CLIENT_ID=...
AMADEUS_CLIENT_SECRET=...
AMADEUS_HOSTNAME=production
ENV

docker compose --profile tools run --rm train    # build the model
docker compose up -d                             # serve it
curl http://127.0.0.1:8000/healthz
```

`compose` publishes to `127.0.0.1:8000` only. To reach it from the network,
change the port mapping to `8000:8000` **and** make sure the host firewall
limits it to your internal range.

The `fares` container refreshes prices daily and rotates the long tail weekly.
Drop it from the compose file if you are running offline.

## Option B — systemd on a Linux VM

Unit files are in [`deploy/systemd/`](deploy/systemd/).

```bash
sudo useradd --system --home /var/lib/tcf --create-home tcf
sudo mkdir -p /opt/tcf /var/lib/tcf/{data,models} /etc/tcf
sudo chown -R tcf:tcf /var/lib/tcf

sudo git clone <your-internal-mirror>/TFC.git /opt/tcf
cd /opt/tcf
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt gunicorn
sudo chown -R tcf:tcf /opt/tcf

# Credentials and settings, readable only by the service account
sudo tee /etc/tcf/tcf.env >/dev/null <<'ENV'
AMADEUS_CLIENT_ID=...
AMADEUS_CLIENT_SECRET=...
AMADEUS_HOSTNAME=production
TCF_ALLOWANCE_BASIS=dest
ENV
sudo chmod 640 /etc/tcf/tcf.env && sudo chown root:tcf /etc/tcf/tcf.env

# Data in, model built
sudo -u tcf cp /path/to/sap_export.csv       /var/lib/tcf/data/travel_data.csv
sudo -u tcf cp /path/to/allowance_rates.xlsx /var/lib/tcf/data/daily_allowance.xlsx
sudo -u tcf TCF_DATA_DIR=/var/lib/tcf/data TCF_MODELS_DIR=/var/lib/tcf/models \
     /opt/tcf/.venv/bin/python cli.py train --evaluate

sudo cp deploy/systemd/* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tcf-web.service
sudo systemctl enable --now tcf-fares-daily.timer tcf-fares-weekly.timer
sudo systemctl enable --now tcf-retrain.timer
```

Then restrict the port to your internal network:

```bash
sudo ufw allow from 10.0.0.0/8 to any port 8000 proto tcp
```

Check it: `systemctl status tcf-web`, `journalctl -u tcf-web -f`,
`systemctl list-timers 'tcf-*'`.

## Option C — Windows server

`waitress` is the WSGI server to use on Windows; gunicorn does not run there.

```powershell
py -m venv C:\tcf\.venv
C:\tcf\.venv\Scripts\pip install -r requirements.txt waitress

$env:TCF_DATA_DIR   = "C:\tcf\data"
$env:TCF_MODELS_DIR = "C:\tcf\models"
C:\tcf\.venv\Scripts\python cli.py train --evaluate

C:\tcf\.venv\Scripts\waitress-serve --listen=0.0.0.0:8000 wsgi:application
```

To run it as a service, wrap that last command with
[NSSM](https://nssm.cc/) or `sc.exe create`. Use Task Scheduler for the
recurring jobs, mirroring the systemd timers:

| Task | Schedule | Command |
|---|---|---|
| Daily fares | 06:00 daily | `python cli.py refresh-fares --cadence daily` |
| Weekly fares | 03:00 Sunday | `python cli.py refresh-fares --cadence weekly` |
| Retrain | 02:00 on the 1st | `python cli.py train --evaluate` then restart the service |

Note that `waitress-serve` is single-process with a thread pool, so `--preload`
has no equivalent and none is needed.

## Updating the data

The export is a file. Replacing it and retraining is the whole workflow:

```bash
sudo -u tcf cp new_export.csv /var/lib/tcf/data/travel_data.csv
sudo systemctl start tcf-retrain.service     # trains, then restarts the web service
```

`tcf-retrain` runs monthly on its own. Run it by hand after dropping in a new
export rather than waiting.

If the business would rather manage the export themselves, point `TCF_DATA_DIR`
at a OneDrive/SharePoint-synced folder on the server and let them replace the
file there — the retrain timer will pick it up. The sync client reads it as an
ordinary file under the signed-in user's permissions; the app makes no call to
SharePoint or Graph.

## Monitoring

`GET /healthz` returns enough to spot a stale deployment:

```json
{
  "status": "ok",
  "trips": 33000,
  "model_trained_at": "2026-09-01T02:00:31+00:00",
  "fare_quotes": 412,
  "fare_last_refresh": "2026-09-20T06:00:12+00:00",
  "offline_mode": false
}
```

Worth alerting on:

- `model_trained_at` older than ~6 weeks — the retrain timer has stopped
- `fare_last_refresh` older than `TCF_MAX_AGE_DAYS` (default 30) — quotes have
  gone stale and airfare has silently fallen back to history alone
- the endpoint not answering at all

## Upgrading

```bash
cd /opt/tcf && sudo -u tcf git pull
sudo /opt/tcf/.venv/bin/pip install -r requirements.txt
sudo systemctl start tcf-retrain.service    # rebuild the model, restart the web service
```

Always retrain after an upgrade. The model is a pickle of the classes in this
repository, so a model built by an older version may not load into a newer one —
and `wsgi.py` will refuse to start rather than serve something broken.

## Backups

Back up `/var/lib/tcf/data`. The model and fare cache are rebuildable —
the export and the allowance sheet are the only irreplaceable files, and the
export is itself a re-runnable SAP report.
