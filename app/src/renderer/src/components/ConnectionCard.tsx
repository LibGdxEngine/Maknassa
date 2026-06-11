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
    <section className="rounded-[10px] border border-[rgba(255,255,255,0.06)] bg-[#131926] p-4 shadow-[0_1px_3px_rgba(0,0,0,0.4),0_4px_12px_rgba(0,0,0,0.25)]">
      <h2 className="mb-3 text-[10px] font-semibold uppercase tracking-[0.1em] text-[#4e5d73]">
        Facebook Account
      </h2>

      {connected ? (
        <div className="flex items-center gap-2 rounded-lg border border-[rgba(52,211,153,0.35)] bg-[rgba(52,211,153,0.08)] px-3 py-2 text-xs text-[#34d399]">
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#34d399]" />
          <span className="font-medium">Connected</span>
          {session?.account_id && (
            <span className="ml-auto font-mono text-[10px] text-[#4e5d73]">
              {session.account_id}
            </span>
          )}
        </div>
      ) : (
        <p className="text-[11px] leading-relaxed text-[#4e5d73]">
          Sign in once. A real browser window opens — log in to Facebook there, then return
          here. Your session stays on this device and is never uploaded.
        </p>
      )}

      <button
        type="button"
        onClick={connect}
        disabled={phase.kind === 'running'}
        className="mt-3 flex w-full items-center justify-center gap-2 rounded-[8px] bg-[#1d4ed8] px-3 py-2 text-xs font-semibold text-white transition-all duration-150 hover:bg-[#2563eb] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-[#3b82f6] focus-visible:outline-offset-2"
        style={{ backgroundImage: 'linear-gradient(to bottom, rgba(255,255,255,0.07) 0%, transparent 100%)' }}
      >
        {phase.kind === 'running' ? (
          <>
            <span className="h-3.5 w-3.5 rounded-full border-2 border-white border-t-transparent animate-spin" />
            Waiting for login…
          </>
        ) : (
          <>
            <span>🔑</span>
            {connected ? 'Reconnect to Facebook' : 'Connect to Facebook'}
          </>
        )}
      </button>

      {phase.kind === 'running' && (
        <p className="mt-2 text-[11px] leading-snug text-[#4e5d73]">
          A browser window has opened — complete the Facebook sign-in there.
        </p>
      )}
      {phase.kind === 'timeout' && (
        <p className="mt-2 rounded-lg border border-[rgba(251,191,36,0.35)] bg-[rgba(251,191,36,0.08)] px-3 py-2 text-[11px] text-[#fbbf24]">
          Didn&apos;t detect a login in time. Click <strong>Connect to Facebook</strong> again.
        </p>
      )}
      {phase.kind === 'error' && (
        <p className="mt-2 rounded-lg border border-[rgba(248,113,113,0.35)] bg-[rgba(248,113,113,0.08)] px-3 py-2 text-[11px] text-[#f87171]">
          Login failed: {phase.message}
        </p>
      )}
    </section>
  )
}
