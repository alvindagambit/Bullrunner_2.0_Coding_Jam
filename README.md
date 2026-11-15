# Bullrunner 2.0

A live map of USF's Bull Runner campus shuttles. It shows the route lines, the stops, and every bus that is currently running, with how full each bus is. Positions refresh every 5 seconds.

Started as a USF Coding Jam project at a Google DevFest hackathon. It is now maintained by Alvin Lopez.

## Live deployment

| | URL |
|---|---|
| App (frontend) | <https://bullrunner-2-0-coding-jam.vercel.app> |
| Backend API | <https://bullrunner-2-0-coding-jam-xzak.vercel.app/buses> |

Both are deployed on Vercel from `main`. Outside service hours (nights, weekends) the API correctly returns `[]` and the map shows "No active buses".

## Architecture

```
Browser ──► React/Vite frontend ──/api/buses──► Flask backend ──► PassioGo API
            (Leaflet map,          (Vite proxy     (/buses: filter,    (USF system 2343)
             side panel)            or Vercel       validate GPS,
                                    rewrite)        compute load)
            routes.json / stops.json ◄── gtfs/convert_gtfs.py (USF GTFS feed)
```

- **Backend**: Python 3, Flask (`app.py`, `passio_client.py`). It reads live vehicle data from PassioGo, drops out-of-service buses and invalid coordinates, and returns a small JSON contract. See [`BACKEND.md`](BACKEND.md), the source of truth for the API.
- **Frontend**: React 19, Vite, Tailwind, Leaflet (`frontend/`). See [`frontend/README.md`](frontend/README.md).
- **Static map data**: route shapes and stops converted from USF's GTFS feed by `gtfs/convert_gtfs.py` into `frontend/public/`.
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
| `GET /buses` | Implemented. Returns `[{ id, lat, lng, route, color, load, outdatedGps, ... }]`. `load` is a percentage from 0 to 100, or `null` when unavailable. `outdatedGps` is a boolean. Upstream failures return `502`. |
| `GET /alerts` | **Not implemented** (returns `404`; the frontend treats that as no alerts) |

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
```

## Known limitations

- **Stale GPS isn't shown**: the backend flags stale positions with `outdatedGps`, but the map doesn't display it yet, so those buses look live.
- **No alerts**: `/alerts` is not implemented.
- **MSC Express has no route line**: the route exists in PassioGo but not in the GTFS data, so its buses appear without a line.
- **No CI**: tests and lint only run locally. Vercel builds each PR, but it doesn't run the tests.
- **No caching**: every frontend poll (each tab, every 5 s) reaches PassioGo.
- **PassioGo 0.2.2 bug**: `Vehicle` objects have broken coordinates, so `passio_client.py` reads the raw API instead of using `getVehicles()`.
- **GTFS regeneration** needs `pandas`, which isn't in `requirements.txt` because the app doesn't use it at runtime. `gtfs/routes.json` and `gtfs/stops.json` are an older output format used only by `gtfs/check_routes.py`. The app uses `frontend/public/`.

## Contributors

From the original hackathon team (see the git history for details):

- **Alvin Lopez**: Flask backend and live PassioGo integration, deployment
- **Sebastian Mejia**: frontend map (Vite, React, Tailwind, Leaflet)
- **Anna Victoria**: side panel dashboard and alerts polling
- **Carlos Cruz**: GTFS route and stop data, and the converter
