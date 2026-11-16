import { useState } from 'react'
import BusMap from './components/Map'
import SidePanel from './components/SidePanel'
import { useAlerts } from './hooks/useAlerts'
import { useBuses } from './hooks/useBuses'
import { useStaticData } from './hooks/useStaticData'

export default function App() {
  const { routes, stops, fromMock: staticFromMock } = useStaticData()
  const { buses, error, isMock, lastUpdated } = useBuses()
  const { alerts, error: alertsError, lastUpdated: alertsUpdated } = useAlerts()
  const [selectedRoute, setSelectedRoute] = useState(null)
  const [focusedStop, setFocusedStop] = useState(null)

  return (
    <div className="flex h-dvh w-screen flex-col overflow-hidden md:flex-row">
      <div className="order-2 h-[46dvh] min-h-0 w-full shrink-0 md:order-1 md:h-full md:w-96">
        <SidePanel
          buses={buses}
          routes={routes}
          selectedRoute={selectedRoute}
          onSelectRoute={setSelectedRoute}
          lastUpdated={lastUpdated}
          alerts={alerts}
          alertsError={alertsError}
          alertsUpdated={alertsUpdated}
          dataError={error}
          isMock={isMock}
          focusedStopId={focusedStop?.id ?? null}
          onViewStop={setFocusedStop}
        />
      </div>

      <main className="relative order-1 h-[54dvh] min-h-0 w-full shrink-0 md:order-2 md:h-full md:min-w-0 md:flex-1">
        <BusMap
          routes={routes}
          stops={stops}
          buses={buses}
          selectedRoute={selectedRoute}
          onSelectRoute={setSelectedRoute}
          focusedStop={focusedStop}
        />

        {focusedStop && (
          <button
            type="button"
            onClick={() => setFocusedStop(null)}
            className="absolute top-3 right-3 z-[1000] cursor-pointer rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-[#006747] shadow-md ring-1 ring-slate-200 hover:bg-slate-50"
          >
            ← Back to full map
          </button>
        )}

        {/* Small dev badge so the team always knows which data the map is showing. */}
        <div className="pointer-events-none absolute bottom-6 left-3 z-[1000] flex flex-col gap-1 text-xs font-medium">
          {(isMock || staticFromMock) && (
            <span className="rounded-full bg-amber-400 px-3 py-1 text-amber-950 shadow">
              Mock data: {[isMock && 'buses', staticFromMock && 'routes/stops'].filter(Boolean).join(' + ')}
            </span>
          )}
          {error && (
            <span className="rounded-full bg-red-600 px-3 py-1 text-white shadow">
              Can&apos;t reach backend: {error.message}
            </span>
          )}
        </div>
      </main>
    </div>
  )
}
