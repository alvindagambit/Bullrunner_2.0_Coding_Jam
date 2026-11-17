// App-wide settings. Override them in frontend/.env (see .env.example).

/** Use Vercel's same-origin /api proxy by default; override for local development. */
export const API_URL = (import.meta.env.VITE_API_URL ?? '/api').replace(/\/$/, '')

/**
 * true  -> use the fake buses in src/mock/ (demo mode)
 * false -> call GET {API_URL}/buses
 */
export const USE_MOCK = (import.meta.env.VITE_USE_MOCK ?? 'false') === 'true'

/** Initial map view: USF Tampa campus. */
export const USF_CENTER = [28.0587, -82.4139]
export const DEFAULT_ZOOM = 15

/** How often to refresh bus positions. */
export const BUS_POLL_MS = 5000

/** How often to refresh service alerts. */
export const ALERTS_POLL_MS = 60000
