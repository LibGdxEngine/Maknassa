// Reactor grid + controls row. Pure selection math lives in lib/selection; this
// component renders the responsive card grid, the select-all/deselect-all controls,
// the per-reaction-type filter chips, and the live selected count.

import { ReactorCard } from './ReactorCard'
import { reactionEmoji } from '../lib/reactions'
import {
  clearAll,
  filteredKeys,
  reactionCounts,
  reactionTypes,
  selectAll,
  toggle
} from '../lib/selection'
import type { UIReactor } from '../lib/types'

interface ReactorGridProps {
  reactors: UIReactor[]
  selected: Set<string>
  activeFilters: Set<string>
  search: string
  blockedKeys: Set<string>
  hideBlocked: boolean
  selectedCount: number
  onSelectedChange: (next: Set<string>) => void
  onFiltersChange: (next: Set<string>) => void
  onSearchChange: (next: string) => void
  onToggleHideBlocked: () => void
}

export function ReactorGrid({
  reactors,
  selected,
  activeFilters,
  search,
  blockedKeys,
  hideBlocked,
  selectedCount,
  onSelectedChange,
  onFiltersChange,
  onSearchChange,
  onToggleHideBlocked
}: ReactorGridProps) {
  const matched = new Set(filteredKeys(reactors, activeFilters, search))
  // "Hide blocked" further narrows the matched set; visibleKeys (post-hide) is what
  // Select all / Deselect all act on, so they never touch a hidden, already-blocked row.
  const visible = reactors.filter(
    (r) => matched.has(r.profile_key) && (!hideBlocked || !blockedKeys.has(r.profile_key))
  )
  const visibleKeys = new Set(visible.map((r) => r.profile_key))
  const blockedCount = reactors.reduce((n, r) => n + (blockedKeys.has(r.profile_key) ? 1 : 0), 0)
  const types = reactionTypes(reactors)
  const counts = reactionCounts(reactors)

  return (
    <section className="space-y-3">
      {/* Controls bar */}
      <div className="flex flex-wrap items-center gap-1.5">
        <div className="relative">
          <span className="pointer-events-none absolute inset-y-0 left-2.5 flex items-center text-[#4e5d73]">
            <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 11a6 6 0 11-12 0 6 6 0 0112 0z" />
            </svg>
          </span>
          <input
            type="text"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search by name"
            aria-label="Search reactors by name"
            className="h-[30px] w-44 rounded-[6px] border border-[rgba(255,255,255,0.08)] bg-[#131926] pl-7 pr-6 text-[11px] text-[#e8edf5] placeholder:text-[#4e5d73] outline-none transition focus:border-[rgba(59,130,246,0.5)] focus:ring-2 focus:ring-[rgba(59,130,246,0.12)]"
          />
          {search && (
            <button
              type="button"
              onClick={() => onSearchChange('')}
              aria-label="Clear search"
              className="absolute inset-y-0 right-1.5 flex items-center text-[#4e5d73] hover:text-[#e8edf5] focus-visible:outline-none"
            >
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>

        <span className="mx-0.5 h-4 w-px bg-[rgba(255,255,255,0.08)]" />

        <button
          type="button"
          onClick={() => onSelectedChange(selectAll(selected, [...visibleKeys]))}
          className="chip-toggle rounded-[6px] border border-[rgba(255,255,255,0.08)] bg-[#131926] px-3 py-1.5 text-[11px] font-medium text-[#9aa5b8] hover:border-[rgba(255,255,255,0.16)] hover:text-[#e8edf5] focus-visible:outline-2 focus-visible:outline-[#3b82f6] focus-visible:outline-offset-1"
        >
          Select all
        </button>
        <button
          type="button"
          onClick={() => onSelectedChange(clearAll(selected, [...visibleKeys]))}
          className="chip-toggle rounded-[6px] border border-[rgba(255,255,255,0.08)] bg-[#131926] px-3 py-1.5 text-[11px] font-medium text-[#9aa5b8] hover:border-[rgba(255,255,255,0.16)] hover:text-[#e8edf5] focus-visible:outline-2 focus-visible:outline-[#3b82f6] focus-visible:outline-offset-1"
        >
          Deselect all
        </button>

        <span className="mx-1 h-4 w-px bg-[rgba(255,255,255,0.08)]" />

        {types.map((type) => {
          const active = activeFilters.has(type)
          return (
            <button
              key={type}
              type="button"
              onClick={() => onFiltersChange(toggle(activeFilters, type))}
              aria-pressed={active}
              className={[
                'chip-toggle rounded-full border px-2.5 py-1 text-[11px] focus-visible:outline-2 focus-visible:outline-[#3b82f6] focus-visible:outline-offset-1',
                active
                  ? 'border-[rgba(59,130,246,0.5)] bg-[rgba(59,130,246,0.12)] text-[#60a5fa]'
                  : 'border-[rgba(255,255,255,0.08)] bg-[#131926] text-[#9aa5b8] hover:border-[rgba(255,255,255,0.16)] hover:text-[#e8edf5]',
              ].join(' ')}
            >
              {reactionEmoji(type)}{' '}
              <span className="font-medium">{type}</span>
              <span className="ml-1 tabular-nums text-[#4e5d73]">({counts[type] ?? 0})</span>
            </button>
          )
        })}

        {blockedCount > 0 && (
          <button
            type="button"
            onClick={onToggleHideBlocked}
            aria-pressed={hideBlocked}
            className={[
              'chip-toggle ml-auto rounded-full border px-2.5 py-1 text-[11px] focus-visible:outline-2 focus-visible:outline-[#3b82f6] focus-visible:outline-offset-1',
              hideBlocked
                ? 'border-[rgba(59,130,246,0.5)] bg-[rgba(59,130,246,0.12)] text-[#60a5fa]'
                : 'border-[rgba(255,255,255,0.08)] bg-[#131926] text-[#9aa5b8] hover:border-[rgba(255,255,255,0.16)] hover:text-[#e8edf5]'
            ].join(' ')}
          >
            🚫 {hideBlocked ? 'Blocked hidden' : 'Hide blocked'}
            <span className="ml-1 tabular-nums text-[#4e5d73]">({blockedCount})</span>
          </button>
        )}

        <span className={`${blockedCount > 0 ? '' : 'ml-auto'} text-[11px] font-medium text-[#4e5d73] tabular-nums`}>
          <span className="text-[#9aa5b8]">{selectedCount}</span> selected
        </span>
      </div>

      {/* Card grid */}
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
        {visible.map((reactor) => (
          <ReactorCard
            key={reactor.profile_key}
            reactor={reactor}
            selected={selected.has(reactor.profile_key)}
            blocked={blockedKeys.has(reactor.profile_key)}
            onToggle={() => onSelectedChange(toggle(selected, reactor.profile_key))}
          />
        ))}
      </div>

      {visible.length === 0 && (
        <div className="flex flex-col items-center justify-center py-10 text-center">
          <p className="text-sm text-[#4e5d73]">
            {search.trim()
              ? `No reactors match “${search.trim()}”.`
              : 'No reactors match the active filter.'}
          </p>
        </div>
      )}
    </section>
  )
}
