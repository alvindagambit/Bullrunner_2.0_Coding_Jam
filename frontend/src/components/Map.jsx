import 'leaflet/dist/leaflet.css'
import { DomEvent } from 'leaflet'
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMapEvents } from 'react-leaflet'
import { DEFAULT_ZOOM, USF_CENTER } from '../config'

/** Clicking empty map clears the route filter. */
function BackgroundClick({ onClick }) {
  useMapEvents({ click: onClick })
  return null
}

function formatLoad(load) {
  if (!Number.isFinite(load)) return null
  // CONTRACT assumption: load is 0-1 (share of seats taken).
  return `${Math.round(load * 100)}% full`
}

/**
 * The live Bull Runner map.
 *
 * Props (all data follows CONTRACT.md):
 *   routes        [{ id, name, color, points: [[lat, lng], ...] }]
 *   stops         [{ id, name, lat, lng }]
 *   buses         [{ id, lat, lng, route, color, load }]
 *   selectedRoute route name to highlight, or null for all
 *   onSelectRoute called with a route name (or null) when the user clicks a line / the map
 */
export default function BusMap({ routes, stops, buses, selectedRoute = null, onSelectRoute = () => {} }) {
  const isDimmed = (routeName) => selectedRoute !== null && routeName !== selectedRoute

  return (
    <MapContainer center={USF_CENTER} zoom={DEFAULT_ZOOM} className="h-full w-full" zoomControl>
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        maxZoom={19}
      />

      <BackgroundClick onClick={() => onSelectRoute(null)} />

      {/* Route lines */}
      {routes.map((route) => (
        <Polyline
          key={route.id}
          positions={route.points}
          pathOptions={{
            color: route.color,
            weight: selectedRoute === route.name ? 7 : 5,
            opacity: isDimmed(route.name) ? 0.15 : 0.85,
          }}
          eventHandlers={{
            click: (e) => {
              DomEvent.stopPropagation(e) // keep the map's "click empty space" handler from also firing
              onSelectRoute(selectedRoute === route.name ? null : route.name)
            },
          }}
        >
          <Tooltip sticky>{route.name}</Tooltip>
        </Polyline>
      ))}

      {/* Stops */}
      {stops.map((stop) => (
        <CircleMarker
          key={stop.id}
          center={[stop.lat, stop.lng]}
          radius={4}
          pathOptions={{ color: '#334155', weight: 1.5, fillColor: '#ffffff', fillOpacity: 1 }}
        >
          <Tooltip direction="top" offset={[0, -4]}>
            {stop.name}
          </Tooltip>
        </CircleMarker>
      ))}

      {/* Buses (drawn last so they sit on top) */}
      {buses
        .filter((bus) => !isDimmed(bus.route))
        .map((bus) => (
          <CircleMarker
            key={bus.id}
            center={[bus.lat, bus.lng]}
            radius={9}
            pathOptions={{ color: '#ffffff', weight: 3, fillColor: bus.color, fillOpacity: 1 }}
          >
            <Tooltip direction="top" offset={[0, -10]}>
              <strong>{bus.route}</strong>
              <br />
              Bus {bus.id}
              {formatLoad(bus.load) && ` · ${formatLoad(bus.load)}`}
            </Tooltip>
          </CircleMarker>
        ))}
    </MapContainer>
  )
}
