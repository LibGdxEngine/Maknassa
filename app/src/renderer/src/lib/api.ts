// Typed HTTP client for the FastAPI sidecar. Every /api/* call (except health)
// carries the X-Maknassa-Token header the backend printed on its handshake line;
// configureApi seeds the base URL + token from the preload bridge.

import type { JobAccepted } from './types'

let _apiBase = ''
let _token = ''

export function configureApi(apiBase: string, token: string): void {
  _apiBase = apiBase
  _token = token
}

// POST /api/{login,fetch,block,unblock} answer 409 {error:'busy', job_id} when a
// browser job is already running. Surfaced as a typed error so callers can show the
// "another browser task is running" toast without string-matching status codes.
export class BusyError extends Error {
  readonly runningJobId: string | null
  constructor(runningJobId: string | null) {
    super('another browser task is running')
    this.name = 'BusyError'
    this.runningJobId = runningJobId
  }
}

// A non-2xx response that isn't a 409 busy. Carries the status so toasts can tailor
// their wording (e.g. backend-unreachable vs a 500).
export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function baseFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const url = `${_apiBase}${path}`
  const headers = new Headers(options.headers)
  if (_token) {
    headers.set('X-Maknassa-Token', _token)
  }
  return fetch(url, { ...options, headers })
}

export async function get<T>(path: string): Promise<T> {
  const res = await baseFetch(path)
  if (!res.ok) {
    throw new ApiError(res.status, `GET ${path} failed: ${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await baseFetch(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  if (!res.ok) {
    throw new ApiError(res.status, `PUT ${path} failed: ${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await baseFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  if (!res.ok) {
    throw new ApiError(res.status, `POST ${path} failed: ${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

// Start a browser job (login/fetch/block/unblock). Returns the job id from the 202
// envelope, or throws BusyError on a 409 so the caller can surface the busy toast.
export async function postJob(path: string, body: unknown): Promise<string> {
  const res = await baseFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  if (res.status === 409) {
    const data = (await res.json().catch(() => ({}))) as { job_id?: string }
    throw new BusyError(data.job_id ?? null)
  }
  if (!res.ok) {
    throw new ApiError(res.status, `POST ${path} failed: ${res.status} ${res.statusText}`)
  }
  const data = (await res.json()) as JobAccepted
  return data.job_id
}
