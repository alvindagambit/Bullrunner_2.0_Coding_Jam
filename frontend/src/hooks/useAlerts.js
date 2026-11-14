import { fetchAlerts } from '../api'
import { ALERTS_POLL_MS, USE_MOCK } from '../config'
import { usePolling } from './usePolling'

async function getMockAlerts() {
  return []
}

/** Service alerts, refreshed every 60 seconds. */
export function useAlerts() {
  const { data } = usePolling(USE_MOCK ? getMockAlerts : fetchAlerts, ALERTS_POLL_MS)
  return { alerts: data ?? [] }
}
