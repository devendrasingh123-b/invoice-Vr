const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

/**
 * Local dev calls `/api/...` and Vite proxies that to the backend.
 * On Vercel, VITE_API_URL is the ECS API origin and the `/api` prefix is removed.
 */
export function apiUrl(path: string): string {
  if (!API_BASE) return path
  const backendPath = path.replace(/^\/api(?=\/|$)/, '') || '/'
  return `${API_BASE}${backendPath.startsWith('/') ? backendPath : `/${backendPath}`}`
}

export function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(apiUrl(path), init)
}
