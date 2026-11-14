# Bull Runner Live: frontend

React + Vite + Tailwind + Leaflet. Shows the Bull Runner routes, stops and live buses on a map of USF.

## Run it

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

The map works right away with **mock data** (a real sample recorded from Passio). An amber badge in the bottom-left corner shows when mock data is in use.

## Switch to the real backend

Copy `.env.example` to `.env`:

```bash
VITE_API_URL=http://localhost:8000   # where the FastAPI backend runs
VITE_USE_MOCK=false                  # call GET /buses instead of mock data
```

Restart `npm run dev` after changing `.env`.

## Where the data comes from

| Data | Source | Fallback while it doesn't exist yet |
| --- | --- | --- |
| Route lines | `public/routes.json` (Carlos's GTFS script) | `src/mock/routes.json` |
| Stops | `public/stops.json` (Carlos's GTFS script) | `src/mock/stops.json` |
| Buses, every 5 s | `GET {VITE_API_URL}/buses` (backend) | `src/mock/mockBuses.js` (moves buses along their routes) |

All shapes follow `CONTRACT.md`:

```
GET /buses   -> [{ id, lat, lng, route, color, load }]
routes.json  -> [{ id, name, color, points: [[lat, lng], ...] }]
stops.json   -> [{ id, name, lat, lng }]
```

`route` in `/buses` must match `name` in `routes.json` exactly; otherwise route filtering won't line up.

## Files

```
src/
  App.jsx                 layout; holds selectedRoute state; slot for <SidePanel />
  components/Map.jsx      the Leaflet map (routes, stops, buses)
  hooks/usePolling.js     generic "call every N ms" hook (reuse it for /alerts)
  hooks/useBuses.js       buses every 5 s (mock or backend)
  hooks/useStaticData.js  loads routes.json + stops.json once
  api.js                  fetchBuses()
  config.js               API URL, mock switch, USF center, poll interval
  mock/                   sample data in the contract format
```

## Map interactions

- Hover a line, stop or bus to see its name (buses also show how full they are).
- Click a route line to highlight it and hide the other routes' buses. Click it again, or click the empty map, to show everything.
