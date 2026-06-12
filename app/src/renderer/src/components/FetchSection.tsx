// Main fetch panel: post URL input + "Fetch reactors". Runs the fetch job, shows a
// skeleton grid while running, and renders a completeness summary meter on done.

import { useState } from 'react'
import { BusyError } from '../lib/api'
import { startJob } from '../lib/jobs'
import { fetchTypesPayload, reactionCounts, toggleFetchType } from '../lib/selection'
import { REACTION_TYPES, reactionEmoji } from '../lib/reactions'
import type { FetchResult, UIReactor } from '../lib/types'

interface FetchSectionProps {
  reactors: UIReactor[] | null
  expectedTotal: number
  onResult: (result: FetchResult) => void
  onError: (message: string) => void
  onBusy: () => void
}

export function FetchSection({
  reactors,
  expectedTotal,
  onResult,
  onError,
  onBusy
}: FetchSectionProps) {
  const [postUrl, setPostUrl] = useState('')
  const [running, setRunning] = useState(false)
  // Reaction types to fetch; an empty set means "All" (the default fetch).
  const [fetchTypes, setFetchTypes] = useState<Set<string>>(new Set())
  // Whether the result on screen came from a narrowed fetch (for the empty-state copy).
  const [lastFetchFiltered, setLastFetchFiltered] = useState(false)

  async function fetchReactors(): Promise<void> {
    const url = postUrl.trim()
    if (!url) {
      onError('Paste a post URL first.')
      return
    }
    const types = fetchTypesPayload(fetchTypes, REACTION_TYPES)
    setRunning(true)
    try {
      const handle = await startJob<FetchResult>(
        '/api/fetch',
        types ? { post_url: url, reaction_types: types } : { post_url: url }
      )
      const job = await handle.promise
      if (job.state === 'done' && job.result) {
        setLastFetchFiltered(types !== null)
        onResult(job.result)
      } else if (job.state === 'cancelled') {
        onError('Fetch was cancelled.')
      } else {
        onError(job.error ?? 'Fetch failed.')
      }
    } catch (err) {
      if (err instanceof BusyError) {
        onBusy()
      } else {
        onError(String(err instanceof Error ? err.message : err))
      }
    } finally {
      setRunning(false)
    }
  }

  return (
    <section className="space-y-4">
      {/* URL input + button row */}
      <div className="flex flex-col gap-2.5 sm:flex-row">
        <div className="relative flex-1">
          <div className="pointer-events-none absolute inset-y-0 left-3 flex items-center">
            <svg className="h-3.5 w-3.5 text-[#4e5d73]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
            </svg>
          </div>
          <input
            type="text"
            value={postUrl}
            onChange={(e) => setPostUrl(e.target.value)}
            placeholder="https://www.facebook.com/.../posts/..."
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !running) fetchReactors()
            }}
            className="h-10 w-full rounded-[10px] border border-[rgba(255,255,255,0.08)] bg-[#131926] pl-9 pr-3 text-sm text-[#e8edf5] placeholder:text-[#4e5d73] outline-none transition focus:border-[rgba(59,130,246,0.5)] focus:ring-2 focus:ring-[rgba(59,130,246,0.12)] focus:bg-[#1a2235]"
          />
        </div>
        <button
          type="button"
          onClick={fetchReactors}
          disabled={running}
          className="flex h-10 items-center justify-center gap-2 rounded-[10px] bg-[#1d4ed8] px-5 text-sm font-semibold text-white transition-all duration-150 hover:bg-[#2563eb] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-[#3b82f6] focus-visible:outline-offset-2 whitespace-nowrap"
          style={{ backgroundImage: 'linear-gradient(to bottom, rgba(255,255,255,0.07) 0%, transparent 100%)' }}
        >
          {running ? (
            <>
              <span className="h-3.5 w-3.5 rounded-full border-2 border-white border-t-transparent animate-spin" />
              Fetching…
            </>
          ) : (
            'Fetch reactors'
          )}
        </button>
      </div>

      {/* Which reaction types to fetch: "All" (empty selection) or a subset. */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] font-medium text-[#4e5d73]">Reactions</span>
        <FetchTypeChip
          label="All"
          active={fetchTypes.size === 0}
          disabled={running}
          onClick={() => setFetchTypes(new Set())}
        />
        {REACTION_TYPES.map((type) => (
          <FetchTypeChip
            key={type}
            label={`${reactionEmoji(type)} ${type}`}
            active={fetchTypes.has(type)}
            disabled={running}
            onClick={() => setFetchTypes(toggleFetchType(fetchTypes, type, REACTION_TYPES))}
          />
        ))}
      </div>

      {/* Skeleton grid while fetching */}
      {running && (
        <div className="space-y-3">
          <p className="text-xs text-[#4e5d73]">
            Opening the post and collecting reactors… (a browser window may open)
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonCard key={i} delay={i * 0.08} />
            ))}
          </div>
        </div>
      )}

      {/* Summary meter after fetch */}
      {reactors !== null && !running && (
        <SummaryMeter reactors={reactors} expectedTotal={expectedTotal} filtered={lastFetchFiltered} />
      )}
    </section>
  )
}

function FetchTypeChip({
  label,
  active,
  disabled,
  onClick
}: {
  label: string
  active: boolean
  disabled: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active}
      className={[
        'chip-toggle rounded-full border px-2.5 py-1 text-[11px] font-medium focus-visible:outline-2 focus-visible:outline-[#3b82f6] focus-visible:outline-offset-1 disabled:cursor-not-allowed disabled:opacity-50',
        active
          ? 'border-[rgba(59,130,246,0.5)] bg-[rgba(59,130,246,0.12)] text-[#60a5fa]'
          : 'border-[rgba(255,255,255,0.08)] bg-[#131926] text-[#9aa5b8] hover:border-[rgba(255,255,255,0.16)] hover:text-[#e8edf5]'
      ].join(' ')}
    >
      {label}
    </button>
  )
}

function SkeletonCard({ delay }: { delay: number }) {
  return (
    <div
      className="flex items-center gap-3 rounded-[10px] border border-[rgba(255,255,255,0.06)] bg-[#131926] p-3 skeleton-pulse"
      style={{ animationDelay: `${delay}s` }}
    >
      <div className="h-11 w-11 shrink-0 rounded-full bg-[#1a2235]" />
      <div className="flex-1 space-y-2">
        <div className="h-3 w-3/4 rounded-full bg-[#1a2235]" />
        <div className="h-2.5 w-1/2 rounded-full bg-[#1a2235]" />
      </div>
    </div>
  )
}

function SummaryMeter({
  reactors,
  expectedTotal,
  filtered
}: {
  reactors: UIReactor[]
  expectedTotal: number
  filtered: boolean
}) {
  const captured = reactors.length
  const counts = reactionCounts(reactors)
  const shortfall = expectedTotal > 0 && captured < expectedTotal
  const headline =
    expectedTotal > 0
      ? `${captured} of ${expectedTotal} reactors captured`
      : `${captured} reactor${captured === 1 ? '' : 's'}`

  if (captured === 0 && expectedTotal === 0) {
    return (
      <p className="text-xs text-[#4e5d73]">
        {filtered
          ? 'No reactors found for the selected reaction types.'
          : 'No reactors found for that post.'}
      </p>
    )
  }

  return (
    <div
      className={`rounded-[10px] border px-4 py-3 ${
        shortfall
          ? 'border-[rgba(251,191,36,0.35)] bg-[rgba(251,191,36,0.06)]'
          : 'border-[rgba(255,255,255,0.06)] bg-[#131926]'
      }`}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className={`text-sm font-semibold tabular-nums ${shortfall ? 'text-[#fbbf24]' : 'text-[#e8edf5]'}`}>
          {headline}
        </span>
      </div>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {Object.entries(counts)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([type, n]) => (
            <span
              key={type}
              className="inline-flex items-center gap-1 rounded-full border border-[rgba(255,255,255,0.08)] bg-[#1a2235] px-2.5 py-0.5 text-[11px] text-[#9aa5b8] tabular-nums"
            >
              {reactionEmoji(type)} <span className="text-[#e8edf5] font-medium">{n}</span> {type}
            </span>
          ))}
      </div>
      {shortfall && (
        <p className="mt-2 text-[11px] leading-snug text-[#fbbf24]/80">
          {expectedTotal - captured} reactor(s) not captured. Facebook may have throttled
          scrolling, or some accounts are deleted. Try re-fetching.
        </p>
      )}
    </div>
  )
}
