// Block flow. Sticky bar appears when N>0: "Block selected (N)" -> inline confirm ->
// /api/block job with live progress (done/total + streaming outcome rows) + Cancel.
// On done: Blocked/Failed summary; each blocked row offers Unblock (same job UX).

import { useRef, useState } from 'react'
import { BusyError } from '../lib/api'
import { cancelJob, startJob } from '../lib/jobs'
import { notify, setTaskbarProgress } from '../lib/desktop'
import { outcomeIcon } from '../lib/reactions'
import type { BlockOutcome, Job, JobProgress } from '../lib/types'

interface BlockBarProps {
  selectedCount: number
  selectedUrls: string[]
  // profile_key AND profile_url -> name, so outcome rows (which carry no name from
  // the by-URL block path) can still show a human label. See App.tsx.
  names: Record<string, string>
  // Persist a finished real block run / an individual unblock into the blocklist.
  onBlocked: (outcomes: BlockOutcome[]) => void
  onUnblocked: (key: string) => void
  onBusy: () => void
  onError: (message: string) => void
}

type Phase =
  | { kind: 'idle' }
  | { kind: 'confirm' }
  | { kind: 'running'; jobId: string; done: number; total: number; outcomes: BlockOutcome[]; cancelling: boolean; preview: boolean }
  | { kind: 'results'; outcomes: BlockOutcome[]; cancelled: boolean; preview: boolean }

export function BlockBar({
  selectedCount,
  selectedUrls,
  names,
  onBlocked,
  onUnblocked,
  onBusy,
  onError
}: BlockBarProps) {
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })
  // Track unblock-in-flight per profile_key so individual rows show a spinner.
  const [unblocking, setUnblocking] = useState<Set<string>>(new Set())
  // "Preview only" toggle on the confirm step: a dry run rehearses the block.
  const [preview, setPreview] = useState(false)
  const handleRef = useRef<{ abort(): void } | null>(null)

  function readProgress(job: Job<unknown, JobProgress>): {
    done: number
    total: number
    outcomes: BlockOutcome[]
  } {
    const p = job.progress ?? {}
    return { done: p.done ?? 0, total: p.total ?? 0, outcomes: p.outcomes ?? [] }
  }

  async function runBlock(dryRun: boolean): Promise<void> {
    const urls = selectedUrls
    if (urls.length === 0) return
    setPhase({ kind: 'running', jobId: '', done: 0, total: urls.length, outcomes: [], cancelling: false, preview: dryRun })
    try {
      const handle = await startJob<unknown, JobProgress>(
        '/api/block',
        { profile_urls: urls, dry_run: dryRun },
        {
          onUpdate: (job) => {
            const { done, total, outcomes } = readProgress(job)
            // A preview finishes instantly; only a real, minutes-long block batch
            // earns a taskbar bar the user can watch from another window.
            if (!dryRun) setTaskbarProgress(total > 0 ? done / total : 0)
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
      if (!dryRun) {
        setTaskbarProgress(-1)
        const blocked = outcomes.filter((o) => o.status === 'blocked').length
        const failed = outcomes.length - blocked
        notify(
          'Block finished',
          `Blocked ${blocked} of ${outcomes.length}${failed ? ` — ${failed} failed` : ''}${
            job.state === 'cancelled' ? ' (cancelled)' : ''
          }`
        )
        onBlocked(outcomes) // persists the 'blocked' ones into the blocklist
      }
      setPhase({ kind: 'results', outcomes, cancelled: job.state === 'cancelled', preview: dryRun })
    } catch (err) {
      handleRef.current = null
      if (!dryRun) setTaskbarProgress(-1)
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
      if (last?.status === 'unblocked') onUnblocked(key) // drop from the blocklist
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
    setPreview(false) // a fresh selection starts as a real block, not a preview
  }

  if (phase.kind === 'idle' && selectedCount === 0) return null

  return (
    <div className="sticky bottom-4 z-40 mt-4 rounded-[14px] border border-[rgba(255,255,255,0.08)] bg-[#0e1420]/95 p-4 shadow-[0_4px_24px_rgba(0,0,0,0.6),0_1px_4px_rgba(0,0,0,0.4)] backdrop-blur-md">
      {phase.kind === 'idle' && (
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm text-[#9aa5b8]">
            <span className="font-semibold tabular-nums text-[#e8edf5]">{selectedCount}</span> selected
          </span>
          <button
            type="button"
            onClick={() => setPhase({ kind: 'confirm' })}
            disabled={selectedCount === 0}
            className="rounded-[8px] bg-[#dc2626] px-4 py-2 text-sm font-semibold text-white transition-all duration-150 hover:bg-[#ef4444] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-[#f87171] focus-visible:outline-offset-2"
            style={{ backgroundImage: 'linear-gradient(to bottom, rgba(255,255,255,0.07) 0%, transparent 100%)' }}
          >
            Block selected ({selectedCount})
          </button>
        </div>
      )}

      {phase.kind === 'confirm' && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-2">
            <p className="text-sm text-[#fbbf24]">
              {preview ? (
                <>
                  Preview which{' '}
                  <span className="font-semibold tabular-nums">{selectedCount}</span>{' '}
                  account(s) would be blocked — nothing is changed.
                </>
              ) : (
                <>
                  This will block{' '}
                  <span className="font-semibold tabular-nums">{selectedCount}</span>{' '}
                  account(s) from your own account, human-paced.
                </>
              )}
            </p>
            <label className="flex w-fit cursor-pointer items-center gap-2 text-[11px] text-[#9aa5b8] select-none">
              <input
                type="checkbox"
                checked={preview}
                onChange={(e) => setPreview(e.target.checked)}
                className="h-3.5 w-3.5 accent-[#3b82f6]"
              />
              Preview only — don&apos;t actually block
            </label>
          </div>
          <div className="flex gap-2 shrink-0">
            <button
              type="button"
              onClick={() => setPhase({ kind: 'idle' })}
              className="rounded-[8px] border border-[rgba(255,255,255,0.10)] px-4 py-2 text-sm text-[#9aa5b8] transition hover:border-[rgba(255,255,255,0.20)] hover:text-[#e8edf5] focus-visible:outline-2 focus-visible:outline-[#3b82f6] focus-visible:outline-offset-2"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => runBlock(preview)}
              className={[
                'rounded-[8px] px-4 py-2 text-sm font-semibold text-white transition-all active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-offset-2',
                preview
                  ? 'bg-[#2563eb] hover:bg-[#3b82f6] focus-visible:outline-[#3b82f6]'
                  : 'bg-[#dc2626] hover:bg-[#ef4444] focus-visible:outline-[#f87171]'
              ].join(' ')}
              style={{ backgroundImage: 'linear-gradient(to bottom, rgba(255,255,255,0.07) 0%, transparent 100%)' }}
            >
              {preview ? `Preview (${selectedCount})` : `Confirm block (${selectedCount})`}
            </button>
          </div>
        </div>
      )}

      {phase.kind === 'running' && (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-medium text-[#e8edf5]">
              {phase.preview ? 'Previewing…' : 'Blocking…'}{' '}
              <span className="font-mono tabular-nums">{phase.done}</span>
              <span className="text-[#4e5d73]"> / </span>
              <span className="font-mono tabular-nums text-[#9aa5b8]">{phase.total}</span>
            </span>
            <button
              type="button"
              onClick={requestCancel}
              disabled={phase.cancelling}
              className="rounded-[6px] border border-[rgba(255,255,255,0.10)] px-3 py-1.5 text-xs text-[#9aa5b8] transition hover:border-[rgba(255,255,255,0.20)] hover:text-[#e8edf5] disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-[#3b82f6] focus-visible:outline-offset-1"
            >
              {phase.cancelling ? 'Cancelling…' : 'Cancel'}
            </button>
          </div>
          <ProgressBar done={phase.done} total={phase.total} />
          <OutcomeList outcomes={phase.outcomes} names={names} unblocking={unblocking} />
        </div>
      )}

      {phase.kind === 'results' && (
        <ResultsView
          outcomes={phase.outcomes}
          cancelled={phase.cancelled}
          preview={phase.preview}
          liveCount={selectedCount}
          names={names}
          unblocking={unblocking}
          onUnblock={unblockOne}
          onBlockForReal={() => runBlock(false)}
          onDone={reset}
        />
      )}
    </div>
  )
}

function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <div className="relative h-2 w-full overflow-hidden rounded-full bg-[#1a2235]">
      <div
        className="progress-fill h-full rounded-full bg-gradient-to-r from-[#2563eb] to-[#3b82f6]"
        style={{ width: `${pct}%` }}
      />
      {pct > 0 && (
        <span className="absolute inset-0 flex items-center justify-end pr-1 text-[9px] font-mono tabular-nums text-[#60a5fa] leading-none">
          {pct}%
        </span>
      )}
    </div>
  )
}

// A human label for an outcome row. The by-URL block path returns no name, so fall
// back to the name the grid knew for this profile_key/url before showing the raw url.
function outcomeLabel(o: BlockOutcome, names: Record<string, string>): string {
  return (
    o.name || names[o.profile_key] || names[o.profile_url ?? ''] || o.profile_url || '(no url)'
  )
}

function OutcomeList({
  outcomes,
  names,
  unblocking,
  onUnblock
}: {
  outcomes: BlockOutcome[]
  names: Record<string, string>
  unblocking: Set<string>
  onUnblock?: (url: string, key: string) => void
}) {
  if (outcomes.length === 0) return null
  return (
    <ul className="max-h-56 space-y-1 overflow-y-auto pr-0.5">
      {outcomes.map((o, i) => {
        const label = outcomeLabel(o, names)
        return (
        <li
          key={`${o.profile_key}-${i}`}
          className="flex items-center gap-2 rounded-[6px] bg-[#131926] px-2.5 py-1.5 text-xs"
        >
          <span className="shrink-0 text-sm">{outcomeIcon(o.status)}</span>
          <span className="rounded-[4px] bg-[#1a2235] px-1.5 py-0.5 font-mono text-[10px] text-[#4e5d73]">
            {o.status}
          </span>
          {o.profile_url ? (
            <button
              type="button"
              onClick={() => o.profile_url && window.maknassa.openExternal(o.profile_url)}
              className="min-w-0 flex-1 truncate text-left text-[#60a5fa] hover:underline focus-visible:outline-2 focus-visible:outline-[#3b82f6] focus-visible:outline-offset-1"
              title={label}
            >
              {label}
            </button>
          ) : (
            <span className="min-w-0 flex-1 truncate text-[#9aa5b8]">{label}</span>
          )}
          {o.detail && <span className="shrink-0 truncate text-[10px] text-[#4e5d73]">{o.detail}</span>}
          {onUnblock && o.status === 'blocked' && o.profile_url && (
            <button
              type="button"
              onClick={() => onUnblock(o.profile_url as string, o.profile_key)}
              disabled={unblocking.has(o.profile_key)}
              className="shrink-0 rounded-[4px] border border-[rgba(255,255,255,0.08)] px-2 py-0.5 text-[10px] text-[#9aa5b8] transition hover:border-[rgba(255,255,255,0.16)] hover:text-[#e8edf5] disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-[#3b82f6] focus-visible:outline-offset-1"
            >
              {unblocking.has(o.profile_key) ? 'Unblocking…' : 'Unblock'}
            </button>
          )}
        </li>
        )
      })}
    </ul>
  )
}

function ResultsView({
  outcomes,
  cancelled,
  preview,
  liveCount,
  names,
  unblocking,
  onUnblock,
  onBlockForReal,
  onDone
}: {
  outcomes: BlockOutcome[]
  cancelled: boolean
  preview: boolean
  liveCount: number
  names: Record<string, string>
  unblocking: Set<string>
  onUnblock: (url: string, key: string) => void
  onBlockForReal: () => void
  onDone: () => void
}) {
  const blocked = outcomes.filter((o) => o.status === 'blocked').length
  const failed = outcomes.length - blocked
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 text-sm">
          {preview ? (
            <span className="font-semibold text-[#60a5fa] tabular-nums">
              👁️ {outcomes.length} would be blocked
            </span>
          ) : (
            <>
              <span className="font-semibold text-[#34d399] tabular-nums">
                ✓ {blocked} blocked
              </span>
              {failed > 0 && (
                <span className="text-[#f87171] tabular-nums">✗ {failed} failed</span>
              )}
            </>
          )}
          {cancelled && <span className="text-[#fbbf24]">(cancelled)</span>}
        </div>
        <div className="flex shrink-0 gap-2">
          {preview && !cancelled && liveCount > 0 && (
            <button
              type="button"
              onClick={onBlockForReal}
              className="rounded-[6px] bg-[#dc2626] px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-[#ef4444] active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-[#f87171] focus-visible:outline-offset-1"
              style={{ backgroundImage: 'linear-gradient(to bottom, rgba(255,255,255,0.07) 0%, transparent 100%)' }}
            >
              Block for real ({liveCount})
            </button>
          )}
          <button
            type="button"
            onClick={onDone}
            className="rounded-[6px] border border-[rgba(255,255,255,0.10)] px-3 py-1.5 text-xs text-[#9aa5b8] transition hover:border-[rgba(255,255,255,0.20)] hover:text-[#e8edf5] focus-visible:outline-2 focus-visible:outline-[#3b82f6] focus-visible:outline-offset-1"
          >
            Done
          </button>
        </div>
      </div>
      <OutcomeList outcomes={outcomes} names={names} unblocking={unblocking} onUnblock={onUnblock} />
    </div>
  )
}
