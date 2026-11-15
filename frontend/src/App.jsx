import { useState } from 'react'
import BusMap from './components/Map'
import SidePanel from './components/SidePanel'
import { useAlerts } from './hooks/useAlerts'
import { useBuses } from './hooks/useBuses'
import { useStaticData } from './hooks/useStaticData'

export default function App() {
  const { routes, stops, fromMock: staticFromMock } = useStaticData()
  const { buses, error, isMock, lastUpdated } = useBuses()
  const { alerts } = useAlerts()
  const [selectedRoute, setSelectedRoute] = useState(null)

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <SidePanel
        buses={buses}
        routes={routes}
        selectedRoute={selectedRoute}
        onSelectRoute={setSelectedRoute}
        lastUpdated={lastUpdated}
        alerts={alerts}
        dataError={error}
        isMock={isMock}
      />

      <main className="relative flex-1">
        <BusMap
          routes={routes}
          stops={stops}
          buses={buses}
          selectedRoute={selectedRoute}
          onSelectRoute={setSelectedRoute}
        />

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
