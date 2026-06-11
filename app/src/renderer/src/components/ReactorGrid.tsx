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
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => onSelectedChange(selectAll(selected, [...visibleKeys]))}
          className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs font-medium text-slate-200 transition hover:border-white/20"
        >
          Select all
        </button>
        <button
          type="button"
          onClick={() => onSelectedChange(clearAll(selected, [...visibleKeys]))}
          className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs font-medium text-slate-200 transition hover:border-white/20"
        >
          Deselect all
        </button>

        <div className="mx-1 h-5 w-px bg-white/10" />

        {types.map((type) => {
          const active = activeFilters.has(type)
          return (
            <button
              key={type}
              type="button"
              onClick={() => onFiltersChange(toggle(activeFilters, type))}
              aria-pressed={active}
              className={`rounded-full border px-2.5 py-1 text-xs transition ${
                active
                  ? 'border-sky-500/60 bg-sky-500/15 text-sky-200'
                  : 'border-white/10 bg-white/[0.03] text-slate-300 hover:border-white/20'
              }`}
            >
              {reactionEmoji(type)} {type} ({counts[type] ?? 0})
            </button>
          )
        })}

        <span className="ml-auto text-xs font-medium text-slate-300">{selectedCount} selected</span>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
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
        <p className="text-sm text-slate-500">No reactors match the active filter.</p>
      )}
    </section>
  )
}
