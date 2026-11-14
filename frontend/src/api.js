// Talks to our backend. Shapes follow CONTRACT.md:
//   GET /buses -> [{ id, lat, lng, route, color, load }]

import { API_URL } from './config'

export async function fetchBuses() {
  const res = await fetch(`${API_URL}/buses`)
  if (!res.ok) throw new Error(`GET /buses failed: HTTP ${res.status}`)
  const buses = await res.json()
  if (!Array.isArray(buses)) throw new Error('GET /buses did not return an array')

  // Make sure numbers are numbers, so the map never gets strings.
  return buses
    .map((b) => ({ ...b, lat: Number(b.lat), lng: Number(b.lng), load: Number(b.load) }))
    .filter((b) => Number.isFinite(b.lat) && Number.isFinite(b.lng))
}

export async function fetchAlerts() {
  const res = await fetch(`${API_URL}/alerts`)
  if (res.status === 404) return []
  if (!res.ok) throw new Error(`GET /alerts failed: HTTP ${res.status}`)
  const alerts = await res.json()
  return Array.isArray(alerts) ? alerts : []
}
