// Fake GET /buses for demo mode only (VITE_USE_MOCK=true); never used in production.
//
// buses.json, routes.json and stops.json in this folder are a REAL sample
// recorded from Passio (USF system 2343), already converted to the
// /buses format (see BACKEND.md). Each call moves every bus a few points along its route,
// so you can see them drive around campus.

import routes from './routes.json'
import seedBuses from './buses.json'

const STEP = 4 // route points to advance per poll

const routeByName = new Map(routes.map((r) => [r.name, r]))

// Start each bus at the point on its route closest to where it really was.
const state = seedBuses.map((bus) => {
  const route = routeByName.get(bus.route)
  let index = 0
  if (route) {
    let best = Infinity
    route.points.forEach(([lat, lng], i) => {
      const d = (lat - bus.lat) ** 2 + (lng - bus.lng) ** 2
      if (d < best) {
        best = d
        index = i
      }
    })
  }
  return { ...bus, index }
})

export async function getMockBuses() {
  return state.map((s) => {
    const route = routeByName.get(s.route)
    if (route) {
      s.index = (s.index + STEP) % route.points.length
      ;[s.lat, s.lng] = route.points[s.index]
    }
    const { index: _index, ...bus } = s
    // Mock fixtures store load as a 0–1 fraction; normalize to the live API's 0–100 percentage.
    return { ...bus, load: bus.load == null ? null : bus.load * 100 }
  })
}
