import { useEffect, useRef, useState } from 'react'

/**
 * Calls `fetcher` right away and then every `intervalMs`.
 * Returns { data, error, lastUpdated }. Keeps the last good data if a call fails.
 *
 * Used by useBuses (every BUS_POLL_MS) and useAlerts (every ALERTS_POLL_MS).
 */
export function usePolling(fetcher, intervalMs) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)

  // Always call the latest fetcher without restarting the timer.
  const fetcherRef = useRef(fetcher)
  useEffect(() => {
    fetcherRef.current = fetcher
  })

  useEffect(() => {
    let cancelled = false

    async function tick() {
      try {
        const result = await fetcherRef.current()
        if (cancelled) return
        setData(result)
        setError(null)
        setLastUpdated(Date.now())
      } catch (err) {
        if (!cancelled) setError(err)
      }
    }

    tick()
    const id = setInterval(tick, intervalMs)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [intervalMs])

  return { data, error, lastUpdated }
}
