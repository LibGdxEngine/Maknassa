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
  selectedCount: number
  onSelectedChange: (next: Set<string>) => void
  onFiltersChange: (next: Set<string>) => void
}

export function ReactorGrid({
  reactors,
  selected,
  activeFilters,
  selectedCount,
  onSelectedChange,
  onFiltersChange
}: ReactorGridProps) {
  const visibleKeys = new Set(filteredKeys(reactors, activeFilters))
  const visible = reactors.filter((r) => visibleKeys.has(r.profile_key))
  const types = reactionTypes(reactors)
  const counts = reactionCounts(reactors)

  return (
    <section className="space-y-3">
      {/* Controls bar */}
      <div className="flex flex-wrap items-center gap-1.5">
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

        <span className="ml-auto text-[11px] font-medium text-[#4e5d73] tabular-nums">
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
            onToggle={() => onSelectedChange(toggle(selected, reactor.profile_key))}
          />
        ))}
      </div>

      {visible.length === 0 && (
        <div className="flex flex-col items-center justify-center py-10 text-center">
          <p className="text-sm text-[#4e5d73]">No reactors match the active filter.</p>
        </div>
      )}
    </section>
  )
}
