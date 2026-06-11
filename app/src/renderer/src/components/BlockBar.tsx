// Block flow. Sticky bar appears when N>0: "Block selected (N)" -> inline confirm ->
// /api/block job with live progress (done/total + streaming outcome rows) + Cancel.
// On done: Blocked/Failed summary; each blocked row offers Unblock (same job UX).

import { useRef, useState } from 'react'
import { BusyError } from '../lib/api'
import { cancelJob, startJob } from '../lib/jobs'
import { outcomeIcon } from '../lib/reactions'
import type { BlockOutcome, Job, JobProgress } from '../lib/types'

interface BlockBarProps {
  selectedCount: number
  selectedUrls: string[]
  onBusy: () => void
  onError: (message: string) => void
}

type Phase =
  | { kind: 'idle' }
  | { kind: 'confirm' }
  | { kind: 'running'; jobId: string; done: number; total: number; outcomes: BlockOutcome[]; cancelling: boolean }
  | { kind: 'results'; outcomes: BlockOutcome[]; cancelled: boolean }

export function BlockBar({ selectedCount, selectedUrls, onBusy, onError }: BlockBarProps) {
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })
  // Track unblock-in-flight per profile_key so individual rows show a spinner.
  const [unblocking, setUnblocking] = useState<Set<string>>(new Set())
  const handleRef = useRef<{ abort(): void } | null>(null)

  function readProgress(job: Job<unknown, JobProgress>): {
    done: number
    total: number
    outcomes: BlockOutcome[]
  } {
    const p = job.progress ?? {}
    return { done: p.done ?? 0, total: p.total ?? 0, outcomes: p.outcomes ?? [] }
  }

  async function runBlock(): Promise<void> {
    const urls = selectedUrls
    if (urls.length === 0) return
    setPhase({ kind: 'running', jobId: '', done: 0, total: urls.length, outcomes: [], cancelling: false })
    try {
      const handle = await startJob<unknown, JobProgress>(
        '/api/block',
        { profile_urls: urls },
        {
          onUpdate: (job) => {
            const { done, total, outcomes } = readProgress(job)
            setPhase((prev) =>
              prev.kind === 'running'
                ? { ...prev, jobId: job.id, done, total: total || prev.total, outcomes }
                : prev
            )
          }
        }
      )
      handleRef.current = handle
      const job = await handle.promise
      const { outcomes } = readProgress(job)
      setPhase({ kind: 'results', outcomes, cancelled: job.state === 'cancelled' })
    } catch (err) {
      handleRef.current = null
      if (err instanceof BusyError) {
        onBusy()
        setPhase({ kind: 'idle' })
        return
      }
      onError(String(err instanceof Error ? err.message : err))
      setPhase({ kind: 'idle' })
    }
  }

  async function requestCancel(): Promise<void> {
    if (phase.kind !== 'running' || !phase.jobId) return
    setPhase({ ...phase, cancelling: true })
    try {
      await cancelJob(phase.jobId)
    } catch (err) {
      onError(String(err instanceof Error ? err.message : err))
    }
  }

  async function unblockOne(url: string, key: string): Promise<void> {
    setUnblocking((prev) => new Set(prev).add(key))
    try {
      const handle = await startJob<unknown, JobProgress>('/api/unblock', { profile_urls: [url] })
      const job = await handle.promise
      const last = (job.progress?.outcomes ?? []).at(-1)
      setPhase((prev) => {
        if (prev.kind !== 'results') return prev
        const outcomes = prev.outcomes.map((o) =>
          o.profile_url === url && last ? last : o
        )
        return { ...prev, outcomes }
      })
    } catch (err) {
      if (err instanceof BusyError) onBusy()
      else onError(String(err instanceof Error ? err.message : err))
    } finally {
      setUnblocking((prev) => {
        const next = new Set(prev)
        next.delete(key)
        return next
      })
    }
  }

  function reset(): void {
    setPhase({ kind: 'idle' })
  }

  if (phase.kind === 'idle' && selectedCount === 0) return null

  return (
    <div className="sticky bottom-0 z-40 mt-4 rounded-xl border border-white/10 bg-[#0f1623]/95 p-4 shadow-2xl backdrop-blur">
      {phase.kind === 'idle' && (
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm text-slate-300">{selectedCount} selected</span>
          <button
            type="button"
            onClick={() => setPhase({ kind: 'confirm' })}
            disabled={selectedCount === 0}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            Block selected ({selectedCount})
          </button>
        </div>
      )}

      {phase.kind === 'confirm' && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-amber-200">
            This will block {selectedCount} account(s) from your own account, human-paced.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setPhase({ kind: 'idle' })}
              className="rounded-lg border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:border-white/20"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={runBlock}
              className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-500"
            >
              Confirm block ({selectedCount})
            </button>
          </div>
        </div>
      )}

      {phase.kind === 'running' && (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-medium text-slate-200">
              Blocking… {phase.done} / {phase.total}
            </span>
            <button
              type="button"
              onClick={requestCancel}
              disabled={phase.cancelling}
              className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-200 transition hover:border-white/20 disabled:opacity-60"
            >
              {phase.cancelling ? 'Cancelling…' : 'Cancel'}
            </button>
          </div>
          <ProgressBar done={phase.done} total={phase.total} />
          <OutcomeList outcomes={phase.outcomes} unblocking={unblocking} />
        </div>
      )}

      {phase.kind === 'results' && (
        <ResultsView
          outcomes={phase.outcomes}
          cancelled={phase.cancelled}
          unblocking={unblocking}
          onUnblock={unblockOne}
          onDone={reset}
        />
      )}
    </div>
  )
}

function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
      <div className="h-full rounded-full bg-sky-500 transition-all" style={{ width: `${pct}%` }} />
    </div>
  )
}

function OutcomeList({
  outcomes,
  unblocking,
  onUnblock
}: {
  outcomes: BlockOutcome[]
  unblocking: Set<string>
  onUnblock?: (url: string, key: string) => void
}) {
  if (outcomes.length === 0) return null
  return (
    <ul className="max-h-60 space-y-1 overflow-y-auto text-xs">
      {outcomes.map((o, i) => (
        <li
          key={`${o.profile_key}-${i}`}
          className="flex items-center gap-2 rounded-lg bg-slate-900/40 px-2.5 py-1.5"
        >
          <span className="shrink-0">{outcomeIcon(o.status)}</span>
          <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
            {o.status}
          </span>
          {o.profile_url ? (
            <button
              type="button"
              onClick={() => o.profile_url && window.maknassa.openExternal(o.profile_url)}
              className="min-w-0 flex-1 truncate text-left text-sky-300 hover:underline"
              title={o.name ?? o.profile_url}
            >
              {o.name || o.profile_url}
            </button>
          ) : (
            <span className="min-w-0 flex-1 truncate text-slate-300">{o.name || '(no url)'}</span>
          )}
          {o.detail && <span className="shrink-0 truncate text-slate-500">— {o.detail}</span>}
          {onUnblock && o.status === 'blocked' && o.profile_url && (
            <button
              type="button"
              onClick={() => onUnblock(o.profile_url as string, o.profile_key)}
              disabled={unblocking.has(o.profile_key)}
              className="shrink-0 rounded border border-white/10 px-2 py-0.5 text-[11px] text-slate-200 transition hover:border-white/20 disabled:opacity-60"
            >
              {unblocking.has(o.profile_key) ? 'Unblocking…' : 'Unblock'}
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}

function ResultsView({
  outcomes,
  cancelled,
  unblocking,
  onUnblock,
  onDone
}: {
  outcomes: BlockOutcome[]
  cancelled: boolean
  unblocking: Set<string>
  onUnblock: (url: string, key: string) => void
  onDone: () => void
}) {
  const blocked = outcomes.filter((o) => o.status === 'blocked').length
  const failed = outcomes.length - blocked
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm">
          <span className="font-semibold text-emerald-300">Blocked: {blocked}</span>
          <span className="mx-2 text-slate-500">·</span>
          <span className="text-slate-300">Failed: {failed}</span>
          {cancelled && <span className="ml-2 text-amber-300">(cancelled)</span>}
        </div>
        <button
          type="button"
          onClick={onDone}
          className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-200 transition hover:border-white/20"
        >
          Done
        </button>
      </div>
      <OutcomeList outcomes={outcomes} unblocking={unblocking} onUnblock={onUnblock} />
    </div>
  )
}
