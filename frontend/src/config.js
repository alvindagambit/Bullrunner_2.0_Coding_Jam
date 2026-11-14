// App-wide settings. Override them in frontend/.env (see .env.example).

/** Backend base URL (FastAPI runs on :8000 per the team plan). */
export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

/**
 * true  -> use the fake buses in src/mock/ (default until the backend is ready)
 * false -> call GET {API_URL}/buses
 */
export const USE_MOCK = (import.meta.env.VITE_USE_MOCK ?? 'true') === 'true'

/** USF Tampa, from the team plan. */
export const USF_CENTER = [28.0587, -82.4139]
export const DEFAULT_ZOOM = 15

/** How often to refresh bus positions. */
export const BUS_POLL_MS = 5000
