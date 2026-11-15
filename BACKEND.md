# Bullrunner 2.0 Backend: Live Buses API

Python Flask backend that serves live USF Bull Runner vehicle positions from
PassioGo (USF system ID `2343`).

This file is the source of truth for the backend API contract. The frontend's
static data formats (`routes.json`, `stops.json`) are documented in
[`frontend/README.md`](frontend/README.md).

## Setup

Requires Python 3 (developed on 3.15). Run from the repo root.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run the server

```bash
flask --app app run --debug --port 5001
```

Use port **5001**. On macOS, port 5000 is taken by the AirPlay Receiver and
returns 403 errors that do not come from Flask.

- Homepage: <http://127.0.0.1:5001/>
- Live buses: <http://127.0.0.1:5001/buses>

`--debug` enables auto-reload for local development. Do not use the Flask
development server in production.

## How the frontend reaches this API

The frontend always calls `/api/buses`. The `/api` prefix is stripped before
the request reaches Flask, so Flask itself serves `/buses`:

| Environment | `/api/*` is handled by | Flask receives |
|---|---|---|
| Local development | Vite proxy (`frontend/vite.config.js`) to `http://127.0.0.1:5001` | `/buses` |
| Production | Vercel rewrite (`frontend/vercel.json`) to the deployed backend | `/buses` |

CORS is not enabled because the browser only ever talks to the frontend's own
origin.

## Test

```bash
# Automated tests (mocked upstream, no network needed)
python -m unittest discover -s tests -v

# Live check (server must be running)
curl -s http://127.0.0.1:5001/buses
```

## `GET /buses`

Returns a JSON array of **in-service** USF buses. When no buses are running
(nights, weekends), it returns an empty array `[]` with status `200`.

### Example response (`200 OK`)

```json
[
  {
    "id": 9811,
    "lat": 28.0656675,
    "lng": -82.412397,
    "route": "Plum",
    "color": "#8f0154",
    "load": 17.5,
    "outdatedGps": false,

    "name": "1801",
    "routeId": "67171",
    "heading": 89.72,
    "updated": "03:26 PM",
    "latitude": 28.0656675,
    "longitude": -82.412397
  }
]
```

### Contract fields

| Field | Type | Description |
|---|---|---|
| `id` | integer | PassioGo bus ID |
| `lat` | number | Latitude (WGS84 decimal degrees) |
| `lng` | number | Longitude (WGS84 decimal degrees) |
| `route` | string or null | Route name, for example `"Plum"` |
| `color` | string or null | Route color as hex, for example `"#8f0154"` |
| `load` | number or null | Occupancy **percentage from 0 to 100**, 1 decimal place. Calculated as `paxLoad / totalCap * 100` and capped at 100. `null` when passenger count or capacity is unavailable. |
| `outdatedGps` | boolean | `true` when PassioGo reports the GPS position as stale. The bus is still included. The frontend marks stale bus positions with muted dashed markers and visible route-panel warnings. |

### Additional fields

The current frontend does not use these.

| Field | Type | Description |
|---|---|---|
| `name` | string or null | Bus display name or number |
| `routeId` | string or null | PassioGo route ID. Note that this is a **string**. |
| `heading` | number or null | Direction of travel in degrees (0 to 360) |
| `updated` | string or null | Last report time as given by PassioGo, for example `"03:26 PM"` (local time, no date) |
| `latitude` / `longitude` | number | Same values as `lat` / `lng`, kept for compatibility |

### Guarantees

- Out-of-service buses are excluded.
- Every returned bus has valid coordinates. Missing, NaN, infinite,
  out-of-range, and `0,0` positions are dropped.
- The response is always valid JSON (never `NaN`).

### Errors

If PassioGo is unreachable, slow (over 5 seconds), or returns an error, the
response is:

```json
{"error": "Failed to fetch live buses"}
```

with status **`502`**. Details are logged on the server only.

## `GET /alerts` (official USF service alerts)

Fetches the [USF GTFS-Realtime service-alert feed](https://passio3.com/usf/passioTransit/gtfs/realtime/serviceAlerts).
Returns `200` with `[{ "id": "1", "name": "Advisory", "message": "Details" }]`,
or `200 []` when the feed reports no active advisories.
Expired and future-dated advisories are excluded. The frontend polls
`/api/alerts` every 60 seconds.

If the feed is unavailable or invalid, the endpoint returns `502` with
`{"error":"Service alerts temporarily unavailable"}`, and the frontend
displays an **alerts unavailable** warning, not a false "no alerts" result.

**Release gate:** Verify real feed access and alert contents on Vercel before
merging this PR.

## Files

| File | Purpose |
|---|---|
| `app.py` | Flask routes: `/`, `/buses`, `/alerts` |
| `gtfs_alerts.py` | Parses official GTFS-Realtime service alerts |
| `tests/test_alerts.py` | Offline alert tests |
| `passio_client.py` | Fetches and validates live bus data from PassioGo |
| `tests/test_buses.py` | Automated tests for `/buses` |
| `requirements.txt` | Pinned backend dependencies |

> **Why not `passiogo.getVehicles()`?** PassioGo 0.2.2 has a bug: its `Vehicle`
> object stores latitude as longitude and drops the real longitude.
> `passio_client.py` reads the raw API response instead. Avoid using `Vehicle`
> objects for coordinates.
