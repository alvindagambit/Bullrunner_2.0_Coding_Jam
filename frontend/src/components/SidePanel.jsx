import { useEffect, useState } from 'react'

/**
 * One active bus inside a route card: its verified next stop and route progress.
 * nextStop / currentStop / direction come from /buses and are null whenever the
 * backend could not establish them reliably; nothing is guessed here.
 */
function BusNextStop({ bus, isFocused, onViewStop }) {
  const { nextStop, currentStop, direction } = bus
  const mapStop = nextStop ?? currentStop
  return (
    <li className={`rounded-lg px-2 py-1.5 ${isFocused ? 'bg-amber-50 ring-1 ring-amber-300' : 'bg-slate-50'}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-semibold tracking-wide text-slate-500 uppercase">Bus {bus.id}</span>
        {bus.outdatedGps === true && <span className="text-[10px] font-semibold text-amber-700">GPS stale</span>}
      </div>
      {currentStop && (
        <div className="text-xs text-slate-700">
          Now at: <span className="font-semibold">{currentStop.name}</span>
        </div>
      )}
      {nextStop ? (
        <>
          <div className="text-sm leading-snug font-bold text-slate-900">Next stop: {nextStop.name}</div>
          <div className="text-[11px] text-slate-500">Stop ID: {nextStop.id}</div>
        </>
      ) : (
        <div className="text-sm font-semibold text-slate-500">Next stop unavailable</div>
      )}
      {/* USF routes are loops, so the trip's end stop is not a useful destination.
          Show progress through the official stop order instead; name a destination
          only for a one-way trip (none exist in USF's current GTFS). */}
      <div className="text-[11px] text-slate-600">
        {direction
          ? `Route progress: Stop ${direction.stopSequence} of ${direction.stopsInTrip}`
          : 'Route progress unavailable'}
      </div>
      {direction && direction.loop === false && (
        <div className="text-[11px] text-slate-600">Heading toward {direction.toward}</div>
      )}
      {mapStop && (
        <button
          type="button"
          onClick={() => onViewStop(mapStop)}
          className="mt-0.5 cursor-pointer text-[11px] font-semibold text-[#006747] hover:underline"
          aria-label={`View ${mapStop.name} on map`}
        >
          View on Map
        </button>
      )}
    </li>
  )
}

/**
 * Control-room side panel for Bull Runner Live.
 *
 * Props (formats: BACKEND.md for buses, frontend/README.md for routes/stops):
 *   buses         [{ id, lat, lng, route, color, load }]
 *   routes        [{ id, name, color, points }]
 *   selectedRoute currently selected route name, or null for all
 *   onSelectRoute callback(routeName | null) to filter the map
 *   lastUpdated   epoch ms timestamp from useBuses
 *   alerts        [{ id, name }]
 *   focusedStopId stop ID currently highlighted on the map, or null
 *   onViewStop    callback({ id, name, lat, lng }) for a bus's "View on Map"
 */
export default function SidePanel({
  buses = [],
  routes = [],
  selectedRoute = null,
  onSelectRoute = () => {},
  lastUpdated = null,
  alerts = [],
  alertsError = null,
  alertsUpdated = null,
  dataError = null,
  isMock = false,
  focusedStopId = null,
  onViewStop = () => {},
}) {
  const [secondsAgo, setSecondsAgo] = useState(0)

  useEffect(() => {
    if (!lastUpdated) return
    const updateTicker = () => {
      setSecondsAgo(Math.max(0, Math.floor((Date.now() - lastUpdated) / 1000)))
    }
    updateTicker()
    const timer = setInterval(updateTicker, 1000)
    return () => clearInterval(timer)
  }, [lastUpdated])

  const liveBusesCount = buses.length
  const staleBusCount = buses.filter((bus) => bus.outdatedGps === true).length
  const activeRoutesCount = new Set(buses.map((b) => b.route).filter(Boolean)).size

  // Backend contract: load is 0–100 percent, or null when unavailable.
  const validLoads = buses
    .map((b) => b.load)
    .filter((load) => typeof load === 'number' && Number.isFinite(load) && load >= 0)

  const avgLoad =
    validLoads.length > 0
      ? Math.round(validLoads.reduce((sum, l) => sum + l, 0) / validLoads.length)
      : 0

  const busCountByRoute = buses.reduce((acc, bus) => {
    if (bus.route) acc[bus.route] = (acc[bus.route] || 0) + 1
    return acc
  }, {})

  return (
    // The whole panel scrolls as one at every size, so routes stay reachable however
    // much height the header, stats and banners take (phones, landscape, short windows).
    // On a tall desktop everything fits and nothing scrolls.
    <aside className="z-10 flex h-full min-h-0 w-full flex-col overflow-y-auto overscroll-contain border-t border-slate-200 bg-white shadow-lg select-none md:border-t-0 md:border-r">
      {/* USF Header */}
      <div className="flex flex-col gap-1 border-b-4 border-[#CFC096] bg-[#006747] p-4 text-white">
        <div className="flex items-center justify-between">
          <h1 className="flex items-center gap-2 text-xl font-bold tracking-tight">
            <span className="inline-block h-3 w-3 animate-pulse rounded-full bg-emerald-400" />
            Bull Runner Live
          </h1>
          <span className="rounded bg-white/20 px-2 py-0.5 text-[10px] font-semibold tracking-wider text-white uppercase">
            USF Transit
          </span>
        </div>
        <div className="mt-1 flex items-center justify-between text-xs text-emerald-100">
          <span>Live Tracking Dashboard</span>
          <span className="font-mono text-emerald-200">
            {lastUpdated ? `Updated ${secondsAgo}s ago` : 'Connecting...'}
          </span>
        </div>
      </div>

      {/* Alerts status is distinct from "no active alerts". */}
      {alertsError && !isMock && (
        <div role="alert" className="border-b border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
          <strong>Service alerts unavailable.</strong> We cannot confirm whether USF has any current advisories.
        </div>
      )}
      {!alertsError && alertsUpdated && !isMock && alerts.length === 0 && (
        <div role="status" className="border-b border-slate-200 px-4 py-2 text-xs text-slate-500">
          No current service alerts reported.
        </div>
      )}

      {/* Alerts Banner */}
      {alerts.length > 0 && (
        <div className="border-b border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-900">
          <div className="mb-1 flex items-center gap-1.5 font-semibold text-amber-800">
            <span>Active Transit Alerts</span>
          </div>
          {alerts.map((alert) => (
            <p key={alert.id ?? alert.name} className="leading-tight">
              {alert.name ?? alert.message ?? 'Service advisory in effect.'}
              {alert.message && alert.message !== alert.name && (
                <span className="mt-1 block font-normal whitespace-pre-line">{alert.message}</span>
              )}
            </p>
          ))}
        </div>
      )}

      {/* Stat Cards */}
      <div className="grid grid-cols-3 gap-2 border-b border-slate-200 bg-slate-50 p-4">
        <div className="rounded-lg border border-slate-200 bg-white p-3 text-center shadow-sm">
          <span className="block text-[10px] font-bold tracking-wider text-slate-500 uppercase">
            Buses Live
          </span>
          <span className="text-2xl font-black text-[#006747]">{liveBusesCount}</span>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-3 text-center shadow-sm">
          <span className="block text-[10px] font-bold tracking-wider text-slate-500 uppercase">
            Active Routes
          </span>
          <span className="text-2xl font-black text-[#006747]">{activeRoutesCount}</span>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-3 text-center shadow-sm">
          <span className="block text-[10px] font-bold tracking-wider text-slate-500 uppercase">
            Avg Load
          </span>
          <span className="text-2xl font-black text-[#006747]">{validLoads.length ? `${avgLoad}%` : '—'}</span>
        </div>
      </div>

      {staleBusCount > 0 && (
        <div role="status" className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-900">
          <strong>GPS signal delayed:</strong> {staleBusCount} bus{staleBusCount === 1 ? "" : "es"} reported with an outdated location. Verify positions before relying on them.
        </div>
      )}

      {!isMock && lastUpdated && !dataError && buses.length === 0 && (
        <div role="status" className="border-b border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          No active buses reported right now. Routes and stops remain available.
        </div>
      )}

      {/* Route List Filter */}
      <div className="flex flex-none flex-col gap-2 p-4 md:flex-1">
        <div className="mb-1 flex items-center justify-between">
          <h2 className="text-xs font-bold tracking-wider text-slate-500 uppercase">
            Campus Routes ({routes.length})
          </h2>
          {selectedRoute && (
            <button
              type="button"
              onClick={() => onSelectRoute(null)}
              className="cursor-pointer text-xs font-semibold text-[#006747] hover:underline"
            >
              Reset filter
            </button>
          )}
        </div>

        {routes.map((route) => {
          const isSelected = selectedRoute === route.name
          const busCount = busCountByRoute[route.name] || 0
          const hasBuses = busCount > 0
          const staleOnRoute = buses.filter((bus) => bus.route === route.name && bus.outdatedGps === true).length
          const routeBuses = buses
            .filter((bus) => bus.route === route.name)
            .sort((a, b) => String(a.id).localeCompare(String(b.id), undefined, { numeric: true }))

          return (
            <div
              key={route.id ?? route.name}
              className={`overflow-hidden rounded-xl border transition-all ${
                isSelected
                  ? 'border-[#006747] bg-[#006747]/10 shadow-sm ring-1 ring-[#006747]'
                  : 'border-slate-200 bg-white hover:border-slate-300'
              }`}
            >
              <button
                type="button"
                onClick={() => onSelectRoute(isSelected ? null : route.name)}
                className={`flex w-full cursor-pointer items-center justify-between p-3 text-left ${
                  isSelected ? '' : 'hover:bg-slate-50'
                }`}
              >
                <div className="flex items-center gap-3">
                  <span
                    className="h-4 w-4 shrink-0 rounded-full border border-black/10 shadow-sm"
                    style={{ backgroundColor: route.color || '#006747' }}
                  />
                  <div>
                    <div className="text-sm leading-tight font-semibold text-slate-900">
                      {route.name}
                    </div>
                    <div className="text-[11px] text-slate-500">
                      {hasBuses ? `${busCount} bus${busCount > 1 ? 'es' : ''} running` : 'No active buses'}
                    </div>
                    {staleOnRoute > 0 && (
                      <div className="text-[11px] font-semibold text-amber-700">
                        {staleOnRoute} GPS stale
                      </div>
                    )}
                  </div>
                </div>

                {hasBuses ? (
                  <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800">
                    {busCount} active
                  </span>
                ) : (
                  <span className="text-xs text-slate-400">Idle</span>
                )}
              </button>

              {routeBuses.length > 0 && (
                <ul className="flex flex-col gap-2 border-t border-slate-200/80 px-3 pt-2 pb-3">
                  {routeBuses.map((bus) => (
                    <BusNextStop
                      key={bus.id}
                      bus={bus}
                      isFocused={focusedStopId != null && [bus.nextStop?.id, bus.currentStop?.id].includes(focusedStopId)}
                      onViewStop={onViewStop}
                    />
                  ))}
                </ul>
              )}
            </div>
          )
        })}
      </div>

      {/* Footer */}
      <div className="border-t border-slate-200 bg-slate-100 p-3 text-center text-[11px] text-slate-500">
        Bull Runner Live &bull; Built for USF Bulls
      </div>
    </aside>
  )
}
