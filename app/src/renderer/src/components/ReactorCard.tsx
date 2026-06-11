// One reactor card: avatar (graceful fallback to initials / 👤), name (click opens the
// profile in the OS browser), reaction emoji+label chip, selection checkbox.

import { useState } from 'react'
import { reactionEmoji } from '../lib/reactions'
import type { UIReactor } from '../lib/types'

interface ReactorCardProps {
  reactor: UIReactor
  selected: boolean
  onToggle: () => void
}

function initials(name: string | null): string {
  if (!name) return ''
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
}

export function ReactorCard({ reactor, selected, onToggle }: ReactorCardProps) {
  const [imgFailed, setImgFailed] = useState(false)
  const name = reactor.name || '(no name)'
  const showImg = reactor.avatar_url && !imgFailed
  const fallback = initials(reactor.name) || '👤'

  function openProfile(): void {
    if (reactor.profile_url) window.maknassa.openExternal(reactor.profile_url)
  }

  return (
    <div
      className={`flex items-center gap-3 rounded-xl border p-3 transition ${
        selected
          ? 'border-sky-500/60 bg-sky-500/10'
          : 'border-white/10 bg-white/[0.03] hover:border-white/20'
      }`}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        aria-label={`Select ${name}`}
        className="h-4 w-4 shrink-0 accent-sky-500"
      />

      <div className="h-11 w-11 shrink-0 overflow-hidden rounded-full bg-slate-700/60">
        {showImg ? (
          <img
            src={reactor.avatar_url ?? ''}
            alt=""
            onError={() => setImgFailed(true)}
            className="h-full w-full object-cover"
          />
        ) : (
          <span className="flex h-full w-full items-center justify-center text-sm font-medium text-slate-300">
            {fallback}
          </span>
        )}
      </div>

      <div className="min-w-0 flex-1">
        {reactor.profile_url ? (
          <button
            type="button"
            onClick={openProfile}
            className="block max-w-full truncate text-left text-sm font-medium text-sky-300 hover:underline"
            title={name}
          >
            {name}
          </button>
        ) : (
          <span className="block truncate text-sm font-medium text-slate-200" title={name}>
            {name}
          </span>
        )}
        <span className="mt-0.5 inline-flex items-center gap-1 text-xs text-slate-400">
          {reactionEmoji(reactor.reaction_type)} {reactor.reaction_type}
        </span>
      </div>
    </div>
  )
}
