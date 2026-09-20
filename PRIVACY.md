# Data handling

This document states exactly what this application does with data, so it can be
checked rather than taken on trust.

## Summary

Every part of the forecasting pipeline runs on the machine you start it on. The
expense export is read from local disk, the model is trained in local memory,
the trained model is written to local disk, and forecasts are computed locally.

There is exactly one optional outbound call: a public airfare price lookup. It
sends an airport pair and a date. It sends nothing else.

## What never leaves the machine

| Data | Where it lives | Leaves? |
|---|---|---|
| SAP expense export (`travel_data.csv`) | local disk | **No** |
| Report keys, amounts, expense types, dates | local memory and disk | **No** |
| Home and destination countries per trip | local memory and disk | **No** |
| Daily allowance rates | local disk | **No** |
| Trained model (`forecaster.pkl`) | local disk | **No** |
| Forecast requests and results | local memory | **No** |
| Any traveller name or identifier | not read at all | **No** |

The forecaster uses no external inference service, no hosted model endpoint and
no telemetry. There is no analytics, crash reporting or usage tracking in the
codebase.

## The one outbound call

When live fare refresh is enabled, `travel_cost_forecasting/fares/amadeus.py`
sends a request of exactly this shape:

```
GET https://api.amadeus.com/v2/shopping/flight-offers
    ?originLocationCode=ARN
    &destinationLocationCode=PVG
    &departureDate=2026-04-12
    &returnDate=2026-04-19
    &adults=1
    &currencyCode=EUR
    &travelClass=ECONOMY
    &max=20
```

That is the complete payload. It is a market price question about a route, of
the kind any member of the public could ask. It contains:

- no company name, no tenant identifier, no employee data
- no report keys, amounts, or anything derived from the expense export
- no indication that any particular trip is planned, booked, or was ever taken

Routes are chosen by how often they appear in your history, which means the
*set* of routes queried over time reflects where your organisation travels.
If your threat model treats that aggregate pattern as sensitive, turn the
feature off — see below. The queries carry no volumes, costs or dates of
actual travel.

## Turning all network access off

Set the kill switch:

```bash
export TCF_OFFLINE=1
```

With `TCF_OFFLINE` set, no fare provider is constructed, the refresh job exits
immediately, and the Amadeus client raises `OfflineError` rather than opening a
socket — even if credentials are present. The application runs normally and the
airfare component falls back to the historical model. This is enforced in code
and covered by tests (`tests/test_fares.py::test_offline_mode_*`).

Simply not setting `AMADEUS_CLIENT_ID` and `AMADEUS_CLIENT_SECRET` has the same
practical effect: with no credentials, no fare call is ever attempted.

## Feeding fares in without any API

If you want current airfare accuracy but no outbound calls at all, implement
`FareProvider` over a spreadsheet of negotiated corporate rates from your travel
management company. `StaticFareProvider` in `fares/base.py` already does this
and is a working example — point it at your own price table and the rest of the
application behaves identically.

## Where the data files live

By default the export and the allowance sheet are read from
`travel_cost_forecasting/data/`. Set `TCF_DATA_DIR` to read them from elsewhere,
such as a OneDrive or SharePoint-synced folder, so the business can update the
source data without touching the application:

```bash
export TCF_DATA_DIR="/Users/you/OneDrive - Company/Travel Forecasting/data"
```

The file is read through the normal filesystem, by the synced client, under the
signed-in user's existing permissions. The application itself makes no call to
SharePoint, Microsoft Graph, or any other service.

## Where the data sits when several people use it

Running this as one internal service is the better choice for data protection,
not just the easier one. The alternative -- giving each person a copy to run --
means giving each person a copy of the expense export. One server means one
copy, on a host you control, with one set of file permissions.

What the users' browsers receive is a forecast: four numbers and the evidence
behind them. No expense line, report key or traveller detail is ever sent to
the browser.

If you do ever distribute the trained model itself, note that it is aggregate
statistics rather than records -- medians, shrunk route levels and tree splits.
But a route flown only once or twice is thinly represented, and its estimate
will sit close to that single trip's actual cost. Before handing the model file
to anyone who should not see individual trip costs, suppress thin routes so
that any route with fewer than k trips falls back to its destination-country
estimate. That is not implemented today because the current design keeps the
model on the server.

## Committing data

`.gitignore` excludes everything in the data directory except the two small
sample files that ship with the repository. Do not commit a real export.
