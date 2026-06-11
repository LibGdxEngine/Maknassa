let _apiBase = ''
let _token = ''

export function configureApi(apiBase: string, token: string): void {
  _apiBase = apiBase
  _token = token
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
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

export async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await baseFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

type JobStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled'

interface Job {
  id: string
  status: JobStatus
  [key: string]: unknown
}

const TERMINAL_STATES: Set<JobStatus> = new Set(['done', 'failed', 'cancelled'])

export class JobPoller {
  private jobId: string
  private intervalMs: number
  private timerId: ReturnType<typeof setTimeout> | null = null
  private onUpdate: (job: Job) => void
  private onDone: (job: Job) => void
  private onError: (err: Error) => void

  constructor(
    jobId: string,
    callbacks: {
      onUpdate: (job: Job) => void
      onDone: (job: Job) => void
      onError: (err: Error) => void
    },
    intervalMs = 700
  ) {
    this.jobId = jobId
    this.intervalMs = intervalMs
    this.onUpdate = callbacks.onUpdate
    this.onDone = callbacks.onDone
    this.onError = callbacks.onError
  }

  start(): void {
    this.poll()
  }

  stop(): void {
    if (this.timerId !== null) {
      clearTimeout(this.timerId)
      this.timerId = null
    }
  }

  private poll(): void {
    get<Job>(`/api/jobs/${this.jobId}`)
      .then((job) => {
        this.onUpdate(job)
        if (TERMINAL_STATES.has(job.status)) {
          this.onDone(job)
        } else {
          this.timerId = setTimeout(() => this.poll(), this.intervalMs)
        }
      })
      .catch((err: Error) => {
        this.onError(err)
      })
  }
}
