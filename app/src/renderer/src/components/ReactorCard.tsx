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
      role="button"
      tabIndex={0}
      onClick={onToggle}
      onKeyDown={(e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); onToggle() }}}
      aria-pressed={selected}
      aria-label={`${selected ? 'Deselect' : 'Select'} ${name}`}
      className={[
        'reactor-card relative flex items-center gap-3 rounded-[10px] border p-3 cursor-pointer select-none focus-visible:outline-2 focus-visible:outline-[#3b82f6] focus-visible:outline-offset-2',
        selected
          ? 'reactor-card--selected border-[rgba(59,130,246,0.5)] bg-[rgba(59,130,246,0.08)] shadow-[inset_3px_0_0_#3b82f6,0_1px_3px_rgba(0,0,0,0.4)]'
          : 'border-[rgba(255,255,255,0.06)] bg-[#131926] hover:border-[rgba(255,255,255,0.13)] hover:bg-[#161e2e] shadow-[0_1px_3px_rgba(0,0,0,0.3)]',
      ].join(' ')}
    >
      {/* Custom checkbox indicator */}
      <div
        className={[
          'shrink-0 flex h-4 w-4 items-center justify-center rounded-[4px] border transition-all duration-150',
          selected
            ? 'bg-[#3b82f6] border-[#3b82f6]'
            : 'bg-[#1a2235] border-[rgba(255,255,255,0.15)]',
        ].join(' ')}
        aria-hidden="true"
      >
        {selected && (
          <svg className="h-2.5 w-2.5 text-white" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
            <path d="M2 6l3 3 5-5" />
          </svg>
        )}
      </div>

      {/* Avatar with reaction ring */}
      <div className={[
        'relative h-10 w-10 shrink-0 overflow-hidden rounded-full ring-2 ring-offset-1 ring-offset-transparent',
        selected ? 'ring-[#3b82f6]/50' : 'ring-[rgba(255,255,255,0.08)]',
      ].join(' ')}>
        {showImg ? (
          <img
            src={reactor.avatar_url ?? ''}
            alt=""
            onError={() => setImgFailed(true)}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-[#1a2235] text-xs font-semibold text-[#9aa5b8]">
            {fallback}
          </div>
        )}
      </div>

      {/* Name + reaction chip */}
      <div className="min-w-0 flex-1">
        {reactor.profile_url ? (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); openProfile() }}
            className="block max-w-full truncate text-left text-[13px] font-medium text-[#60a5fa] hover:underline focus-visible:outline-2 focus-visible:outline-[#3b82f6] focus-visible:outline-offset-1 leading-tight"
            title={name}
          >
            {name}
          </button>
        ) : (
          <span className="block truncate text-[13px] font-medium text-[#e8edf5] leading-tight" title={name}>
            {name}
          </span>
        )}
        <span className="mt-1 inline-flex items-center gap-1 rounded-full bg-[#1a2235] px-2 py-0.5 text-[10px] text-[#9aa5b8] leading-tight">
          {reactionEmoji(reactor.reaction_type)}
          <span>{reactor.reaction_type}</span>
        </span>
      </div>
    </div>
  )
}
