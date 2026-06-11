// Sidebar connection card: shows session state from /api/session and drives the
// login job. Disconnected -> explainer + Connect button; running -> "waiting for you
// to log in…"; success -> connected badge (re-fetch session); login-timeout ->
// warning with retry guidance; other errors -> error banner.

import { useState } from 'react'
import { get } from '../lib/api'
import { BusyError } from '../lib/api'
import { startJob } from '../lib/jobs'
import type { SessionInfo } from '../lib/types'

type LoginPhase =
  | { kind: 'idle' }
  | { kind: 'running' }
  | { kind: 'timeout' }
  | { kind: 'error'; message: string }

interface ConnectionCardProps {
  session: SessionInfo | null
  onSession: (session: SessionInfo) => void
  onBusy: () => void
}

export function ConnectionCard({ session, onSession, onBusy }: ConnectionCardProps) {
  const [phase, setPhase] = useState<LoginPhase>({ kind: 'idle' })
  const connected = session?.connected ?? false

  async function connect(): Promise<void> {
    setPhase({ kind: 'running' })
    try {
      const handle = await startJob('/api/login', { timeout_s: 120 })
      const job = await handle.promise
      if (job.state === 'done') {
        const fresh = await get<SessionInfo>('/api/session')
        onSession(fresh)
        setPhase({ kind: 'idle' })
      } else if (job.error === 'login-timeout') {
        setPhase({ kind: 'timeout' })
      } else {
        setPhase({ kind: 'error', message: job.error ?? 'Login failed.' })
      }
    } catch (err) {
      if (err instanceof BusyError) {
        onBusy()
        setPhase({ kind: 'idle' })
        return
      }
      setPhase({ kind: 'error', message: String(err instanceof Error ? err.message : err) })
    }
  }

  return (
    <section className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-300">
        Facebook account
      </h2>

      {connected ? (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
          <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-400" />
          <span>Connected (account id {session?.account_id ?? '—'})</span>
        </div>
      ) : (
        <p className="text-xs leading-relaxed text-slate-400">
          Sign in once. A real browser window opens — log in to Facebook there, then return
          here. Your session stays on this device and is never uploaded.
        </p>
      )}

      <button
        type="button"
        onClick={connect}
        disabled={phase.kind === 'running'}
        className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg bg-sky-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {phase.kind === 'running' ? (
          <>
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
            Waiting…
          </>
        ) : (
          <>🔑 {connected ? 'Reconnect to Facebook' : 'Connect to Facebook'}</>
        )}
      </button>

      {phase.kind === 'running' && (
        <p className="mt-2 text-xs text-slate-400">
          Waiting for you to log in in the opened browser window…
        </p>
      )}
      {phase.kind === 'timeout' && (
        <p className="mt-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          Didn&apos;t detect a login in time. Click <strong>Connect to Facebook</strong> again and
          finish signing in.
        </p>
      )}
      {phase.kind === 'error' && (
        <p className="mt-2 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          Login failed: {phase.message}
        </p>
      )}
    </section>
  )
}
