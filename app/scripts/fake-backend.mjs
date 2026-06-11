#!/usr/bin/env node
/**
 * Fake backend for smoke/E2E testing — implements the real contract surface
 * (handshake, token auth, settings, session, fetch/block jobs with progress)
 * with canned data and no Facebook, so the full UI flow can be driven offline.
 *
 * Usage: node scripts/fake-backend.mjs
 * Or:    MAKNASSA_BACKEND_CMD="node scripts/fake-backend.mjs" npm run dev
 */
import http from 'http'
import crypto from 'crypto'

const PORT = parseInt(process.env.FAKE_PORT || '0', 10)
const TOKEN = crypto.randomBytes(16).toString('hex')
const VERSION = '0.0.0-fake'
const BLOCK_MS = parseInt(process.env.FAKE_BLOCK_MS || '350', 10) // per-profile pacing

// Support --parent-pid: exit when parent dies
const parentPidArg = process.argv.indexOf('--parent-pid')
if (parentPidArg !== -1) {
  const parentPid = parseInt(process.argv[parentPidArg + 1], 10)
  if (!isNaN(parentPid)) {
    setInterval(() => {
      try {
        process.kill(parentPid, 0)
      } catch {
        console.error('[fake-backend] parent died, exiting')
        process.exit(0)
      }
    }, 1000)
  }
}

// --- canned state ----------------------------------------------------------
let settings = {
  profile_dir: '/tmp/fake/profiles/facebook',
  headless: false,
  min_delay: 2,
  max_delay: 6,
  stop_after: 0
}
let accountId = null

// A local-only avatar (data URI) for some reactors; others exercise the fallback.
const AVATAR = (hue) =>
  `data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="hsl(${hue},45%,38%)"/><circle cx="32" cy="24" r="11" fill="hsl(${hue},45%,72%)"/><ellipse cx="32" cy="52" rx="18" ry="13" fill="hsl(${hue},45%,72%)"/></svg>`
  )}`

const NAMES = [
  ['Amira Haddad', 'like'], ['Karim Ben Salah', 'angry'], ['Lina Trabelsi', 'haha'],
  ['Omar Gharbi', 'angry'], ['Sofia Mansour', 'love'], ['Youssef Jebali', 'like'],
  ['Nour Chahed', 'sad'], ['Mehdi Ayari', 'angry'], ['Rania Bouzid', 'wow'],
  ['Tarek Sassi', 'like'], ['Ines Maalej', 'haha'], ['Walid Hamdi', 'angry']
]
const REACTORS = NAMES.map(([name, reaction], i) => ({
  name,
  profile_url: `https://www.facebook.com/profile.php?id=10000${i}`,
  profile_key: `10000${i}`,
  reaction_type: reaction,
  avatar_url: i % 3 === 2 ? null : AVATAR((i * 47) % 360) // every third: fallback path
}))

const jobs = new Map()
let running = null
const newJob = (kind) => {
  const job = {
    id: crypto.randomUUID(),
    kind,
    state: 'running',
    progress: {},
    result: null,
    error: null,
    cancelled: false
  }
  jobs.set(job.id, job)
  running = job
  return job
}
const finish = (job, result, error = null) => {
  job.state = job.cancelled ? 'cancelled' : error ? 'error' : 'done'
  job.result = result
  job.error = error
  if (running === job) running = null
}

// --- server ----------------------------------------------------------------
const server = http.createServer((req, res) => {
  const url = new URL(req.url || '/', `http://127.0.0.1:${PORT}`)
  const sendJson = (status, body) => {
    const data = JSON.stringify(body)
    res.writeHead(status, {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(data)
    })
    res.end(data)
  }
  const readBody = (cb) => {
    let body = ''
    req.on('data', (chunk) => (body += chunk))
    req.on('end', () => cb(body ? JSON.parse(body) : {}))
  }
  const guardBusy = () => {
    if (running) {
      sendJson(409, { error: 'busy', job_id: running.id })
      return true
    }
    return false
  }

  if (req.method === 'GET' && url.pathname === '/api/health') {
    sendJson(200, { status: 'ok', version: VERSION })
    return
  }
  if (url.pathname.startsWith('/api/')) {
    if (req.headers['x-maknassa-token'] !== TOKEN) {
      sendJson(401, { error: 'unauthorized' })
      return
    }
  }

  if (req.method === 'GET' && url.pathname === '/api/session') {
    sendJson(200, {
      connected: accountId !== null,
      account_id: accountId,
      default_profile_dir: settings.profile_dir,
      data_dir: '/tmp/fake'
    })
    return
  }
  if (req.method === 'GET' && url.pathname === '/api/settings') {
    sendJson(200, settings)
    return
  }
  if (req.method === 'PUT' && url.pathname === '/api/settings') {
    readBody((patch) => {
      settings = { ...settings, ...patch }
      sendJson(200, settings)
    })
    return
  }

  if (req.method === 'POST' && url.pathname === '/api/login') {
    if (guardBusy()) return
    const job = newJob('login')
    setTimeout(() => {
      accountId = '100012345'
      finish(job, { account_id: accountId })
    }, 800)
    sendJson(202, { job_id: job.id })
    return
  }

  if (req.method === 'POST' && url.pathname === '/api/fetch') {
    if (guardBusy()) return
    const job = newJob('fetch')
    setTimeout(() => finish(job, { reactors: REACTORS, expected_total: 14 }), 1200)
    sendJson(202, { job_id: job.id })
    return
  }

  if (req.method === 'POST' && (url.pathname === '/api/block' || url.pathname === '/api/unblock')) {
    if (guardBusy()) return
    const unblock = url.pathname === '/api/unblock'
    readBody(({ profile_urls = [] }) => {
      const job = newJob(unblock ? 'unblock' : 'block')
      job.progress = { done: 0, total: profile_urls.length, outcomes: [] }
      let i = 0
      const tick = () => {
        if (job.cancelled || i >= profile_urls.length) {
          finish(job, job.progress.outcomes)
          return
        }
        const u = profile_urls[i]
        const fail = !unblock && i === 2 // third block fails, to exercise the failed row
        job.progress.outcomes.push({
          profile_url: u,
          name: REACTORS.find((r) => r.profile_url === u)?.name ?? null,
          status: fail ? 'failed' : unblock ? 'unblocked' : 'blocked',
          detail: fail ? 'confirm dialog never appeared (canned failure)' : null
        })
        job.progress.done = ++i
        setTimeout(tick, BLOCK_MS)
      }
      setTimeout(tick, BLOCK_MS)
      sendJson(202, { job_id: job.id })
    })
    return
  }

  const jobMatch = url.pathname.match(/^\/api\/jobs\/([0-9a-f-]+)(\/cancel)?$/)
  if (jobMatch) {
    const job = jobs.get(jobMatch[1])
    if (!job) {
      sendJson(404, { error: 'not-found' })
      return
    }
    if (req.method === 'POST' && jobMatch[2]) {
      job.cancelled = true
      sendJson(200, { cancelled: true })
      return
    }
    if (req.method === 'GET' && !jobMatch[2]) {
      const { id, kind, state, progress, result, error } = job
      sendJson(200, { id, kind, state, progress, result, error })
      return
    }
  }

  sendJson(404, { error: 'not found' })
})

server.listen(PORT, '127.0.0.1', () => {
  const { port } = server.address()
  process.stdout.write(`MAKNASSA_BACKEND_PORT=${port}\n`)
  process.stdout.write(`MAKNASSA_BACKEND_TOKEN=${TOKEN}\n`)
  console.error(`[fake-backend] listening on 127.0.0.1:${port}`)
})
