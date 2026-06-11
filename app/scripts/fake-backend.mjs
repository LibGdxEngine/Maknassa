#!/usr/bin/env node
/**
 * Fake backend for smoke testing.
 * Usage: node scripts/fake-backend.mjs
 * Or:    MAKNASSA_BACKEND_CMD="node scripts/fake-backend.mjs" npm run dev
 */
import http from 'http'
import crypto from 'crypto'

const PORT = parseInt(process.env.FAKE_PORT || '0', 10)
const TOKEN = crypto.randomBytes(16).toString('hex')
const VERSION = '0.0.0-fake'

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

  // Health endpoint — no auth
  if (req.method === 'GET' && url.pathname === '/api/health') {
    sendJson(200, { status: 'ok', version: VERSION })
    return
  }

  // Auth check for all other /api/* routes
  if (url.pathname.startsWith('/api/')) {
    const incomingToken = req.headers['x-maknassa-token']
    if (incomingToken !== TOKEN) {
      sendJson(401, { error: 'unauthorized' })
      return
    }
  }

  // Echo endpoint
  if (req.method === 'POST' && url.pathname === '/api/echo') {
    let body = ''
    req.on('data', (chunk) => (body += chunk))
    req.on('end', () => {
      try {
        sendJson(200, { echo: JSON.parse(body) })
      } catch {
        sendJson(400, { error: 'invalid json' })
      }
    })
    return
  }

  sendJson(404, { error: 'not found' })
})

server.listen(PORT, '127.0.0.1', () => {
  const { port } = server.address()
  // Print handshake lines (flushed immediately in Node.js stdout)
  process.stdout.write(`MAKNASSA_BACKEND_PORT=${port}\n`)
  process.stdout.write(`MAKNASSA_BACKEND_TOKEN=${TOKEN}\n`)
  console.error(`[fake-backend] listening on 127.0.0.1:${port}`)
})
