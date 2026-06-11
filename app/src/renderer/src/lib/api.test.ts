import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, BusyError, configureApi, get, post, postJob, put } from './api'

interface FetchCall {
  url: string
  init: RequestInit | undefined
}

function mockFetch(responder: (call: FetchCall) => Response): typeof fetch {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    return Promise.resolve(responder({ url: String(input), init }))
  }) as unknown as typeof fetch
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' }
  })
}

beforeEach(() => {
  configureApi('http://127.0.0.1:9999', 'secret-token')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('auth header injection', () => {
  it('sends X-Maknassa-Token on every authed request', async () => {
    const calls: FetchCall[] = []
    vi.stubGlobal(
      'fetch',
      mockFetch((call) => {
        calls.push(call)
        return jsonResponse(200, { ok: true })
      })
    )

    await get('/api/settings')
    await post('/api/fetch', { post_url: 'x' })
    await put('/api/settings', { headless: true })

    expect(calls).toHaveLength(3)
    for (const call of calls) {
      const headers = new Headers(call.init?.headers)
      expect(headers.get('X-Maknassa-Token')).toBe('secret-token')
    }
    expect(calls[0].url).toBe('http://127.0.0.1:9999/api/settings')
  })

  it('omits the header when no token is configured', async () => {
    configureApi('http://127.0.0.1:9999', '')
    let seen: Headers | null = null
    vi.stubGlobal(
      'fetch',
      mockFetch((call) => {
        seen = new Headers(call.init?.headers)
        return jsonResponse(200, {})
      })
    )
    await get('/api/health')
    expect(seen!.has('X-Maknassa-Token')).toBe(false)
  })
})

describe('error handling', () => {
  it('get throws ApiError with the status on a non-2xx response', async () => {
    vi.stubGlobal('fetch', mockFetch(() => jsonResponse(500, { error: 'boom' })))
    await expect(get('/api/session')).rejects.toBeInstanceOf(ApiError)
    await expect(get('/api/session')).rejects.toMatchObject({ status: 500 })
  })
})

describe('postJob', () => {
  it('returns the job id from a 202 envelope', async () => {
    vi.stubGlobal('fetch', mockFetch(() => jsonResponse(202, { job_id: 'job-123' })))
    await expect(postJob('/api/fetch', { post_url: 'x' })).resolves.toBe('job-123')
  })

  it('throws BusyError carrying the running job id on 409', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(() => jsonResponse(409, { error: 'busy', job_id: 'running-1' }))
    )
    const err = await postJob('/api/block', { profile_urls: [] }).catch((e) => e)
    expect(err).toBeInstanceOf(BusyError)
    expect((err as BusyError).runningJobId).toBe('running-1')
  })

  it('throws ApiError on other non-2xx statuses', async () => {
    vi.stubGlobal('fetch', mockFetch(() => jsonResponse(401, { error: 'unauthorized' })))
    await expect(postJob('/api/login', {})).rejects.toBeInstanceOf(ApiError)
  })
})
