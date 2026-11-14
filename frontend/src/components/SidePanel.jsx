import { useEffect, useState } from 'react'

/**
 * Control-room side panel for Bull Runner Live.
 *
 * Props (data shapes follow CONTRACT.md):
 *   buses         [{ id, lat, lng, route, color, load }]
 *   routes        [{ id, name, color, points }]
 *   selectedRoute currently selected route name, or null for all
 *   onSelectRoute callback(routeName | null) to filter the map
 *   lastUpdated   epoch ms timestamp from useBuses
 *   alerts        [{ id, name }]
 */
export default function SidePanel({
  buses = [],
  routes = [],
  selectedRoute = null,
  onSelectRoute = () => {},
  lastUpdated = null,
  alerts = [],
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
  const activeRoutesCount = new Set(buses.map((b) => b.route).filter(Boolean)).size

  // Support both 0-1 (mock/CONTRACT) and 0-100 (backend) load values.
  const validLoads = buses
    .map((b) => (b.load > 1 ? b.load : b.load * 100))
    .filter((l) => Number.isFinite(l) && l >= 0)

  const avgLoad =
    validLoads.length > 0
      ? Math.round(validLoads.reduce((sum, l) => sum + l, 0) / validLoads.length)
      : 0

  const busCountByRoute = buses.reduce((acc, bus) => {
    if (bus.route) acc[bus.route] = (acc[bus.route] || 0) + 1
    return acc
  }, {})

  return (
    <aside className="z-10 flex h-full w-80 shrink-0 flex-col border-r border-slate-200 bg-white shadow-lg select-none md:w-96">
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

      {/* Alerts Banner */}
      {alerts.length > 0 && (
        <div className="border-b border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-900">
          <div className="mb-1 flex items-center gap-1.5 font-semibold text-amber-800">
            <span>Active Transit Alerts</span>
          </div>
          {alerts.map((alert) => (
            <p key={alert.id ?? alert.name} className="leading-tight">
              {alert.name ?? alert.message ?? 'Service advisory in effect.'}
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
          <span className="text-2xl font-black text-[#006747]">{avgLoad}%</span>
        </div>
      </div>

      {/* Route List Filter */}
      <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-4">
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

          return (
            <button
              type="button"
              key={route.id ?? route.name}
              onClick={() => onSelectRoute(isSelected ? null : route.name)}
              className={`flex w-full cursor-pointer items-center justify-between rounded-xl border p-3 text-left transition-all ${
                isSelected
                  ? 'border-[#006747] bg-[#006747]/10 shadow-sm ring-1 ring-[#006747]'
                  : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
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
