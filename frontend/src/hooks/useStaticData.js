import { useEffect, useState } from 'react'
import mockRoutes from '../mock/routes.json'
import mockStops from '../mock/stops.json'

/**
 * Loads the static map data once:
 *   /routes.json -> [{ id, name, color, points: [[lat, lng], ...] }]
 *   /stops.json  -> [{ id, name, lat, lng }]
 *
 * Carlos's GTFS script writes these into frontend/public/. Until they exist,
 * we fall back to the sample in src/mock/ so the map is never empty.
 */
async function loadJson(path, fallback) {
  try {
    const res = await fetch(path)
    const isJson = (res.headers.get('content-type') ?? '').includes('json')
    if (!res.ok || !isJson) throw new Error(`${path} not found`)
    return { data: await res.json(), fromMock: false }
  } catch {
    console.info(`[map] ${path} not available yet, using mock data from src/mock/`)
    return { data: fallback, fromMock: true }
  }
}

export function useStaticData() {
  const [state, setState] = useState({ routes: [], stops: [], loading: true, fromMock: false })

  useEffect(() => {
    let cancelled = false
    Promise.all([loadJson('/routes.json', mockRoutes), loadJson('/stops.json', mockStops)]).then(
      ([routes, stops]) => {
        if (cancelled) return
        setState({
          routes: routes.data,
          stops: stops.data,
          loading: false,
          fromMock: routes.fromMock || stops.fromMock,
        })
      },
    )
    return () => {
      cancelled = true
    }
  }, [])

  return state
}
