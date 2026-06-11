// Main fetch panel: post URL input + "Fetch reactors". Runs the fetch job, shows a
// spinner while running, and renders a completeness summary meter on done.

import { useState } from 'react'
import { BusyError } from '../lib/api'
import { startJob } from '../lib/jobs'
import { reactionCounts } from '../lib/selection'
import { reactionEmoji } from '../lib/reactions'
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

  async function fetchReactors(): Promise<void> {
    const url = postUrl.trim()
    if (!url) {
      onError('Paste a post URL first.')
      return
    }
    setRunning(true)
    try {
      const handle = await startJob<FetchResult>('/api/fetch', { post_url: url })
      const job = await handle.promise
      if (job.state === 'done' && job.result) {
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
      <div className="flex flex-col gap-3 sm:flex-row">
        <input
          type="text"
          value={postUrl}
          onChange={(e) => setPostUrl(e.target.value)}
          placeholder="https://www.facebook.com/.../posts/..."
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !running) fetchReactors()
          }}
          className="flex-1 rounded-lg border border-white/10 bg-slate-900/60 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500"
        />
        <button
          type="button"
          onClick={fetchReactors}
          disabled={running}
          className="flex items-center justify-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {running ? (
            <>
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              Fetching…
            </>
          ) : (
            'Fetch reactors'
          )}
        </button>
      </div>

      {running && (
        <p className="text-xs text-slate-400">
          Opening the post and collecting reactors… (a browser window may open)
        </p>
      )}

      {reactors !== null && !running && (
        <SummaryMeter reactors={reactors} expectedTotal={expectedTotal} />
      )}
    </section>
  )
}

function SummaryMeter({
  reactors,
  expectedTotal
}: {
  reactors: UIReactor[]
  expectedTotal: number
}) {
  const captured = reactors.length
  const counts = reactionCounts(reactors)
  const shortfall = expectedTotal > 0 && captured < expectedTotal
  const headline =
    expectedTotal > 0
      ? `${captured} of ${expectedTotal} reactors captured`
      : `${captured} reactor${captured === 1 ? '' : 's'}`

  if (captured === 0 && expectedTotal === 0) {
    return <p className="text-sm text-slate-400">No reactors found for that post.</p>
  }

  return (
    <div
      className={`rounded-xl border px-4 py-3 ${
        shortfall ? 'border-amber-500/40 bg-amber-500/10' : 'border-white/10 bg-white/[0.03]'
      }`}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className={`text-sm font-semibold ${shortfall ? 'text-amber-200' : 'text-slate-100'}`}>
          {headline}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {Object.entries(counts)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([type, n]) => (
            <span
              key={type}
              className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-slate-900/60 px-2.5 py-1 text-xs text-slate-200"
            >
              {reactionEmoji(type)} {type}: {n}
            </span>
          ))}
      </div>
      {shortfall && (
        <p className="mt-2 text-xs leading-snug text-amber-200/90">
          {expectedTotal - captured} reactor(s) not captured. Facebook may have throttled
          scrolling, or some accounts are deleted/unlinkable. Try re-fetching.
        </p>
      )}
    </div>
  )
}
