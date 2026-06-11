import { spawn, ChildProcess } from 'child_process'
import { app } from 'electron'
import path from 'path'

export interface BackendHandshake {
  port: number
  token: string
}

let child: ChildProcess | null = null

function shellSplit(cmd: string): string[] {
  const args: string[] = []
  let current = ''
  let inQuote: string | null = null

  for (let i = 0; i < cmd.length; i++) {
    const ch = cmd[i]
    if (inQuote) {
      if (ch === inQuote) {
        inQuote = null
      } else {
        current += ch
      }
    } else if (ch === '"' || ch === "'") {
      inQuote = ch
    } else if (ch === ' ' || ch === '\t') {
      if (current) {
        args.push(current)
        current = ''
      }
    } else {
      current += ch
    }
  }
  if (current) args.push(current)
  return args
}

export function spawnBackend(): Promise<BackendHandshake> {
  return new Promise((resolve, reject) => {
    const cmdEnv = process.env.MAKNASSA_BACKEND_CMD
    let command: string
    let args: string[]

    if (cmdEnv) {
      const parts = shellSplit(cmdEnv)
      command = parts[0]
      args = parts.slice(1)
    } else {
      const ext = process.platform === 'win32' ? 'maknassa-backend.exe' : 'maknassa-backend'
      command = path.join(process.resourcesPath, 'backend', ext)
      args = []
    }

    args.push('--parent-pid', String(process.pid))

    console.log('[backend] spawning:', command, args)

    child = spawn(command, args, {
      stdio: ['ignore', 'pipe', 'pipe'],
      // The frozen backend is a console build (stdout carries the handshake);
      // windowsHide stops Windows from flashing a console window for it.
      windowsHide: true
    })

    let port: number | null = null
    let token: string | null = null
    let lineBuffer = ''
    const stderrLines: string[] = []
    let settled = false

    const timeout = setTimeout(() => {
      if (!settled) {
        settled = true
        reject(
          new Error(
            `Backend handshake timed out after 60s. Stderr tail:\n${stderrLines.slice(-20).join('\n')}`
          )
        )
      }
    }, 60_000)

    child.stdout!.on('data', (chunk: Buffer) => {
      lineBuffer += chunk.toString('utf8')
      const lines = lineBuffer.split('\n')
      lineBuffer = lines.pop() ?? ''

      for (const line of lines) {
        const trimmed = line.trim()
        console.log('[backend stdout]', trimmed)

        const portMatch = trimmed.match(/^MAKNASSA_BACKEND_PORT=(\d+)$/)
        if (portMatch) port = parseInt(portMatch[1], 10)

        const tokenMatch = trimmed.match(/^MAKNASSA_BACKEND_TOKEN=(.+)$/)
        if (tokenMatch) token = tokenMatch[1]

        if (port !== null && token !== null && !settled) {
          settled = true
          clearTimeout(timeout)
          resolve({ port, token })
        }
      }
    })

    child.stderr!.on('data', (chunk: Buffer) => {
      const text = chunk.toString('utf8')
      process.stderr.write(`[backend stderr] ${text}`)
      stderrLines.push(...text.split('\n').filter(Boolean))
      if (stderrLines.length > 100) stderrLines.splice(0, stderrLines.length - 100)
    })

    child.on('error', (err) => {
      if (!settled) {
        settled = true
        clearTimeout(timeout)
        reject(new Error(`Failed to spawn backend: ${err.message}`))
      }
    })

    child.on('exit', (code, signal) => {
      console.log('[backend] exited', { code, signal })
      if (!settled) {
        settled = true
        clearTimeout(timeout)
        reject(
          new Error(
            `Backend exited before handshake (code=${code}, signal=${signal}). Stderr:\n${stderrLines.slice(-20).join('\n')}`
          )
        )
      }
    })
  })
}

export function stopBackend(): void {
  if (!child) return
  const c = child
  child = null

  c.kill('SIGTERM')
  const killTimer = setTimeout(() => {
    try {
      c.kill('SIGKILL')
    } catch {
      // already dead
    }
  }, 3000)

  c.on('exit', () => clearTimeout(killTimer))
}

app.on('will-quit', () => stopBackend())
