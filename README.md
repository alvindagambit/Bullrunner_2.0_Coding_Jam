# Bullrunner 2.0

A live map of USF's Bull Runner campus shuttles. It shows the route lines, the stops, and every bus that is currently running, with how full each bus is and its verified next stop. Positions refresh every 5 seconds; official USF service alerts refresh every 60 seconds.

Started as a USF Coding Jam project at a Google DevFest hackathon. It is now maintained by Alvin Lopez.

## Live deployment

| | URL |
|---|---|
| App (frontend) | <https://bullrunner-2-0-coding-jam.vercel.app> |
| Backend API | <https://bullrunner-2-0-coding-jam-xzak.vercel.app/buses> |

Both are deployed on Vercel from `main`. Outside service hours (nights, weekends) the API correctly returns `[]` and the map shows "No active buses".

## Architecture

```
Browser ──► React/Vite frontend ──/api/*──► Flask backend ──► PassioGo API (live buses, USF system 2343)
            (Leaflet map,          (Vite proxy  (/buses, /alerts) ──► USF GTFS-Realtime: vehiclePositions,
             route panel)           or Vercel        │                     serviceAlerts
                                    rewrite)         └── gtfs/*.txt (official static GTFS: stops, trips, stop order)
            routes.json / stops.json ◄── gtfs/convert_gtfs.py (same official GTFS)
```

- **Backend**: Python 3, Flask (`app.py`). `passio_client.py` reads live buses from PassioGo, drops out-of-service buses and invalid coordinates, and computes load. `next_stop.py` adds each bus's verified next stop and route progress from the official GTFS-Realtime `vehiclePositions` feed, checked against the official stop order in `gtfs/*.txt`. `gtfs_alerts.py` serves official USF service alerts. See [`BACKEND.md`](BACKEND.md), the source of truth for the API.
- **Frontend**: React 19, Vite, Tailwind, Leaflet (`frontend/`). On phones the map sits above a scrollable route panel; on wider screens the panel is on the left. See [`frontend/README.md`](frontend/README.md).
- **Static map data**: route shapes and stops converted from USF's GTFS feed by `gtfs/convert_gtfs.py` into `frontend/public/` (used by the browser only).
- **Backend runtime data**: only `gtfs/*.txt`. Vercel's Python builder never bundles `**/public/**` paths, so backend code must not read from `frontend/public/`.
- **API routing**: the frontend always calls `/api/*`. Locally, the Vite dev server proxies it to Flask on port 5001. In production, `frontend/vercel.json` rewrites it to the deployed backend. Either way the `/api` prefix is stripped, and no CORS is needed.

## Local setup

Requirements: Python 3 (developed on 3.15) and Node.js with npm.

```bash
# Backend (from the repo root)
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask --app app run --debug --port 5001

# Frontend (second terminal)
cd frontend
npm install
npm run dev                        # http://localhost:5173
```

Use port **5001** for Flask. On macOS, port 5000 is taken by the AirPlay Receiver.

## Live and mock modes

| Mode | How | Use it when |
|---|---|---|
| **Live** (default) | Nothing to configure. The frontend calls `/api/buses`. | Normal use; needs Flask running locally |
| **Mock** | Create `frontend/.env` with `VITE_USE_MOCK=true`, then restart `npm run dev` | No buses running, offline demos, or PassioGo is down. An amber badge shows mock data is in use. |

`frontend/.env.example` documents the available settings. `.env` files are gitignored.

## API summary

| Endpoint | Status |
|---|---|
| `GET /buses` | Returns `[{ id, lat, lng, route, color, load, outdatedGps, nextStop, currentStop, direction, ... }]`. `load` is a percentage from 0 to 100, or `null` when unavailable. `outdatedGps` is a boolean. `nextStop` / `direction` are `null` unless verified. Upstream failures return `502`. |
| `GET /alerts` | Official USF GTFS-Realtime service alerts (verified in production 2026-11-16). `200 []` means no current alerts; `502` means the feed is unavailable, and the app says so rather than claiming there are none. |

Full field reference: [`BACKEND.md`](BACKEND.md).

## Test and build

```bash
# Backend tests (mocked upstream, no network), from the repo root
python -m unittest discover -s tests -v

# Frontend production build and lint, from frontend/
npm run build
npm run lint

# Live smoke test (Flask and Vite running)
curl -s http://127.0.0.1:5001/buses        # Flask directly
curl -s http://localhost:5173/api/buses    # through the Vite proxy

# Read-only comparison of production next stops with the official GTFS-Realtime feed
python scripts/verify_live_transit.py
```

**Continuous integration:** `.github/workflows/ci.yml` runs on every pull request and every push to `main`:
- backend unit tests on Python 3.15 (offline; upstream feeds are mocked)
- frontend `npm ci`, lint with warnings treated as errors, and a production build, on Node 24 and Node 26

Use `npm ci` (not `npm install`) to reproduce the CI install. If you change frontend dependencies, commit the updated `package-lock.json`, or `npm ci` will fail.

## Release process

`main` is protected by a GitHub ruleset: every change needs a pull request, the three CI checks (`Backend tests (Python 3.15)`, `Frontend lint + build (Node 24)`, `Frontend lint + build (Node 26)`) must pass, and force-pushes and branch deletion are blocked. CI catches code errors. **It does not prove live transit accuracy or Vercel runtime behaviour**, so every release that touches `/buses`, `/alerts` or their data also gets these checks:

1. **Before merging:** CI is green and both Vercel preview builds succeed. Previews are behind Vercel Authentication, so check the backend preview's `/buses` and `/alerts` while logged in to Vercel.
2. **Before merging, record a rollback reference:** the current production commit and frontend bundle name.
3. **After merging, during Bull Runner service hours,** check production `https://bullrunner-2-0-coding-jam-xzak.vercel.app/buses`:
   - eligible buses (those without `outdatedGps: true`) generally have `nextStop` and `direction`
   - a `null` `nextStop` / `direction` for an individual bus is **acceptable** when the validation safeguards reject incomplete or inconsistent data (for example: bus missing from the official feed, stale or distant feed position, route change, stop-order conflict at a loop's start or end), or when the bus is at a stop with no verifiable following stop (`currentStop` set)
   - it is a **failure** only if it is systematic: all eligible buses `null` across several samples during service hours. Use `python scripts/verify_live_transit.py --diagnose-only --samples 12` to see each bus's reason.
   - wherever `direction` is present, `stopPosition` is at most `stopsInTrip`
   - `heading`, `lat`/`lng`, `route` and `load` look right
   - `/alerts` returns 200
   - the frontend shows no "Mock data" badge
4. **Compare with the official sources:** run `python scripts/verify_live_transit.py`, and spot-check a few next stops against the Passio GO tracker. An empty response outside service hours is **not** a successful check.
5. **Check the Vercel runtime logs:** they should show `Next-stop static GTFS loaded: … stops, … routes, … trip patterns` and no repeated `[stage=static]`, `[stage=feed]` or `[stage=validate]` warnings.
6. **If something fails,** use Vercel → Deployments → previous Production deployment → **Instant Rollback**, or merge a `git revert -m 1 <merge commit>` pull request.

## Known limitations

- **Stale GPS is flagged**: buses with `outdatedGps: true` are shown with muted dashed map markers and warnings in the route panel. Their positions may be outdated.
- **Next stop is shown only when verified**: route cards show each bus's next stop and route progress ("Stop X of Y") from USF's official GTFS-Realtime feed, checked against the official stop order. Otherwise they say "Next stop unavailable" / "Route progress unavailable". Arrival times are not shown.
- **Brown route not independently cross-checked**: Brown next stops pass the same live-feed and official stop-order checks as every route, but Passio GO publishes no Brown arrival times, so they can't be compared with the official tracker. They are shown, with the same safeguards; stale or conflicting data shows "Next stop unavailable".
- **MSC Express has no route line**: the route exists in PassioGo but not in the GTFS data, so its buses appear without a line, and without a next stop.
- **No caching**: every frontend poll (each tab, every 5 s) reaches PassioGo.
- **PassioGo 0.2.2 bug**: `Vehicle` objects have broken coordinates, so `passio_client.py` reads the raw API instead of using `getVehicles()`.
- **GTFS regeneration** needs `pandas`, which isn't in `requirements.txt` because the app doesn't use it at runtime. `gtfs/routes.json` and `gtfs/stops.json` are an older output format used only by `gtfs/check_routes.py`. The frontend uses `frontend/public/`; the backend uses `gtfs/*.txt`. The official feed in `gtfs/` is valid until 2026-12-16; refresh all `gtfs/*.txt` files from USF's `google_transit.zip` when a new feed is published.

## Contributors

From the original hackathon team (see the git history for details):

- **Alvin Lopez**: Flask backend and live PassioGo integration, deployment
- **Sebastian Mejia**: frontend map (Vite, React, Tailwind, Leaflet)
- **Anna Victoria**: side panel dashboard and alerts polling
- **Carlos Cruz**: GTFS route and stop data, and the converter
- **Constantine Millan**: backend alerts and backup stops endpoints, CORS middleware, and render deployment.
