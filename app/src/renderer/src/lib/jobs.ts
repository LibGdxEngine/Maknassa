// Job lifecycle: start a browser job, then poll GET /api/jobs/{id} until it reaches a
// terminal state (done | error | cancelled). startJob returns a handle exposing the
// job id, an abort() to stop polling, and a promise that resolves with the terminal
// Job. Components subscribe via onUpdate for live progress (block/unblock outcomes).

import { get, post, postJob } from './api'
import type { Job, JobProgress } from './types'

const TERMINAL_STATES: ReadonlySet<string> = new Set(['done', 'error', 'cancelled'])

export function isTerminal(state: string): boolean {
  return TERMINAL_STATES.has(state)
}

export interface JobHandle<R = unknown, P = JobProgress> {
  jobId: string
  // Resolves with the terminal Job snapshot; rejects only if polling itself errors
  // (network/HTTP). A job that ends in state 'error' resolves (the error is in the
  // envelope), so callers branch on job.state rather than catch.
  promise: Promise<Job<R, P>>
  // Stop polling. The promise rejects with an AbortError unless already settled.
  abort(): void
}

export interface PollOptions<R = unknown, P = JobProgress> {
  intervalMs?: number
  onUpdate?: (job: Job<R, P>) => void
}

// Poll an already-started job to a terminal state. Used both by startJob and by the
// block flow (which needs the id up front to wire its Cancel button).
export function pollJob<R = unknown, P = JobProgress>(
  jobId: string,
  options: PollOptions<R, P> = {}
): JobHandle<R, P> {
  const intervalMs = options.intervalMs ?? 700
  let aborted = false
  let timer: ReturnType<typeof setTimeout> | null = null
  let rejectFn: ((err: Error) => void) | null = null

  const promise = new Promise<Job<R, P>>((resolve, reject) => {
    rejectFn = reject

    const tick = (): void => {
      if (aborted) return
      get<Job<R, P>>(`/api/jobs/${jobId}`)
        .then((job) => {
          if (aborted) return
          options.onUpdate?.(job)
          if (isTerminal(job.state)) {
            resolve(job)
          } else {
            timer = setTimeout(tick, intervalMs)
          }
        })
        .catch((err: Error) => {
          if (aborted) return
          reject(err)
        })
    }

    tick()
  })

  return {
    jobId,
    promise,
    abort(): void {
      if (aborted) return
      aborted = true
      if (timer !== null) {
        clearTimeout(timer)
        timer = null
      }
      rejectFn?.(new DOMException('Job polling aborted', 'AbortError'))
    }
  }
}

// Start a job (POST path) and immediately begin polling it. Throws BusyError (from
// postJob) before returning a handle if a browser job is already running.
export async function startJob<R = unknown, P = JobProgress>(
  path: string,
  body: unknown,
  options: PollOptions<R, P> = {}
): Promise<JobHandle<R, P>> {
  const jobId = await postJob(path, body)
  return pollJob<R, P>(jobId, options)
}

// Request server-side cancellation. The job thread honors it between items, so the
// poll loop will then observe state 'cancelled'.
export async function cancelJob(jobId: string): Promise<void> {
  await post<{ cancelled: boolean }>(`/api/jobs/${jobId}/cancel`, {})
}
