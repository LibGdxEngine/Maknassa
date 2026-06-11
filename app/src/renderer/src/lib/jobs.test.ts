import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { configureApi } from './api'
import { isTerminal, pollJob, startJob } from './jobs'
import type { Job, JobState } from './types'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' }
  })
}

// Queue of poll responses; the mocked fetch returns them in order for /api/jobs/*.
function jobSequence(states: JobState[], progressByTick: Array<Record<string, unknown>> = []): typeof fetch {
  let tick = 0
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/jobs/')) {
      const state = states[Math.min(tick, states.length - 1)]
      const progress = progressByTick[tick] ?? {}
      tick += 1
      const job: Job = {
        id: 'job-1',
        kind: 'block',
        state,
        progress,
        result: state === 'done' ? { ok: true } : null,
        error: state === 'error' ? 'boom' : null
      }
      return Promise.resolve(jsonResponse(200, job))
    }
    // POST start -> 202
    return Promise.resolve(jsonResponse(202, { job_id: 'job-1' }))
  }) as unknown as typeof fetch
}

beforeEach(() => {
  configureApi('http://127.0.0.1:9999', 'tok')
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('isTerminal', () => {
  it('treats done/error/cancelled as terminal and running as not', () => {
    expect(isTerminal('done')).toBe(true)
    expect(isTerminal('error')).toBe(true)
    expect(isTerminal('cancelled')).toBe(true)
    expect(isTerminal('running')).toBe(false)
  })
})

describe('pollJob terminal resolution', () => {
  it('resolves with the done job after running ticks', async () => {
    vi.stubGlobal('fetch', jobSequence(['running', 'running', 'done']))
    const handle = pollJob('job-1', { intervalMs: 700 })
    // Drive the poll loop: each running tick schedules the next via setTimeout.
    await vi.advanceTimersByTimeAsync(2000)
    const job = await handle.promise
    expect(job.state).toBe('done')
  })

  it('resolves (does not reject) when the job ends in error', async () => {
    vi.stubGlobal('fetch', jobSequence(['error']))
    const handle = pollJob('job-1')
    await vi.advanceTimersByTimeAsync(0)
    const job = await handle.promise
    expect(job.state).toBe('error')
    expect(job.error).toBe('boom')
  })

  it('resolves with a cancelled job', async () => {
    vi.stubGlobal('fetch', jobSequence(['running', 'cancelled']))
    const handle = pollJob('job-1')
    await vi.advanceTimersByTimeAsync(700)
    const job = await handle.promise
    expect(job.state).toBe('cancelled')
  })

  it('streams progress through onUpdate before resolving', async () => {
    vi.stubGlobal(
      'fetch',
      jobSequence(
        ['running', 'done'],
        [
          { done: 1, total: 2, outcomes: [{ status: 'blocked' }] },
          { done: 2, total: 2, outcomes: [{ status: 'blocked' }, { status: 'failed' }] }
        ]
      )
    )
    const updates: number[] = []
    const handle = pollJob('job-1', {
      onUpdate: (job) => updates.push((job.progress as { done?: number }).done ?? 0)
    })
    await vi.advanceTimersByTimeAsync(700)
    await handle.promise
    expect(updates).toEqual([1, 2])
  })
})

describe('pollJob abort', () => {
  it('rejects with an AbortError and stops polling', async () => {
    vi.stubGlobal('fetch', jobSequence(['running', 'running', 'running']))
    const handle = pollJob('job-1')
    await vi.advanceTimersByTimeAsync(0)
    handle.abort()
    await expect(handle.promise).rejects.toMatchObject({ name: 'AbortError' })
  })
})

describe('startJob', () => {
  it('posts to start the job then polls it to done', async () => {
    vi.stubGlobal('fetch', jobSequence(['done']))
    const handle = await startJob('/api/fetch', { post_url: 'x' })
    expect(handle.jobId).toBe('job-1')
    await vi.advanceTimersByTimeAsync(0)
    const job = await handle.promise
    expect(job.state).toBe('done')
  })
})
