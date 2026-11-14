import { fetchBuses } from '../api'
import { BUS_POLL_MS, USE_MOCK } from '../config'
import { getMockBuses } from '../mock/mockBuses'
import { usePolling } from './usePolling'

/** Live buses, refreshed every 5 seconds. Uses mock data when VITE_USE_MOCK=true. */
export function useBuses() {
  const { data, error, lastUpdated } = usePolling(USE_MOCK ? getMockBuses : fetchBuses, BUS_POLL_MS)
  return { buses: data ?? [], error, lastUpdated, isMock: USE_MOCK }
}
