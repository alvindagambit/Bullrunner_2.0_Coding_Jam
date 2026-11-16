# Bull Runner Live: frontend

React + Vite + Tailwind + Leaflet. Shows the Bull Runner routes, stops and live buses on a map of USF.

## Run it

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

By default the app shows **live** buses from the Flask backend, so start Flask first (below). A red badge in the bottom-left corner appears if the backend can't be reached. An amber badge appears whenever mock data is in use.

## Use the real backend locally

By default the app calls the live Flask backend at `/api/buses`. In development, Vite proxies `/api/*` to Flask on `http://127.0.0.1:5001` and strips the `/api` prefix, mirroring `vercel.json` in production. No `.env` is needed. Start Flask from the repo root first (first-time setup is in `BACKEND.md`):

```bash
source .venv/bin/activate          # Windows: .venv\Scripts\activate
flask --app app run --debug --port 5001
```

To use mock buses instead (for example, when no buses are running), create `frontend/.env` with `VITE_USE_MOCK=true` and restart `npm run dev`. Don't set `VITE_API_URL` locally unless you are pointing at a different backend.

## Where the data comes from

| Data | Source | Fallback |
| --- | --- | --- |
| Route lines | `public/routes.json` (Carlos's GTFS script, `gtfs/convert_gtfs.py`) | `src/mock/routes.json` if the file can't be loaded |
| Stops | `public/stops.json` (Carlos's GTFS script) | `src/mock/stops.json` if the file can't be loaded |
| Buses, every 5 s | `GET /api/buses` (Flask backend) | `src/mock/mockBuses.js` when `VITE_USE_MOCK=true` (moves buses along their routes) |
| Alerts, every 60 s | `GET /api/alerts` from the official USF GTFS-Realtime feed | On upstream failure, show an unavailable warning; do not claim no advisories. |

### Data formats

The `/buses` contract is defined in [`BACKEND.md`](../BACKEND.md) (the source of truth). That includes `load` (a percentage from 0 to 100, or `null`) and `outdatedGps`. The fields the frontend uses:

```
GET /api/buses -> [{ id, lat, lng, route, color, load, outdatedGps, nextStop, currentStop, direction }]
routes.json    -> [{ id, name, color, points: [[lat, lng], ...] }]
stops.json     -> [{ id, name, lat, lng }]
```

`route` in `/buses` must match `name` in `routes.json` exactly; otherwise route filtering won't line up. `outdatedGps` is used to visually distinguish stale bus locations and show route-level warnings.

Each active route card lists its buses with "Next stop: …", the stop ID, "Heading toward …" and a **View on Map** action. That action centers the map on the stop, highlights it, and shows **Back to full map**; route filtering keeps working. When `nextStop` or `direction` is `null`, the card says "Next stop unavailable" or "Direction unavailable". Mock buses have no next-stop data, so they always show "unavailable".

## Files

```
src/
  App.jsx                   layout; holds selectedRoute state; renders SidePanel + Map
  components/Map.jsx        the Leaflet map (routes, stops, buses)
  components/SidePanel.jsx  route list, bus count, average load, alerts banner (Ana)
  hooks/usePolling.js       generic "call every N ms" hook
  hooks/useBuses.js         buses every 5 s (mock or backend)
  hooks/useAlerts.js        alerts every 60 s
  hooks/useStaticData.js    loads routes.json + stops.json once
  api.js                    fetchBuses(), fetchAlerts()
  config.js                 API URL (default /api), mock switch, USF center, poll intervals
  mock/                     sample data in the formats above
vite.config.js              dev proxy: /api/* -> Flask on 127.0.0.1:5001
vercel.json                 production rewrite: /api/* -> deployed Flask backend
```

## Map interactions

- Hover a line, stop or bus to see its name (buses also show how full they are).
- Click a route line to highlight it and hide the other routes' buses. Click it again, or click the empty map, to show everything.
