// Pure selection logic for the reactor grid. Components stay thin by delegating all
// set math here; vitest covers these directly. Selection is keyed by profile_key.

import type { UIReactor } from './types'

// Profile keys currently visible under the active reaction-type filters and an
// optional case-insensitive name query. An empty filter set means "no type filter"
// and a blank query means "no name filter" -> with both empty, every reactor is
// visible. This is the single visibility choke point, so Select all / Deselect all
// (which operate on visible keys) compose with both filters for free.
export function filteredKeys(
  reactors: UIReactor[],
  activeTypes: ReadonlySet<string>,
  query = ''
): string[] {
  const needle = query.trim().toLowerCase()
  return reactors
    .filter((r) => activeTypes.size === 0 || activeTypes.has(r.reaction_type))
    .filter((r) => needle === '' || (r.name ?? '').toLowerCase().includes(needle))
    .map((r) => r.profile_key)
}

export function toggle(selected: ReadonlySet<string>, key: string): Set<string> {
  const next = new Set(selected)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  return next
}

// Pre-fetch reaction chips: an EMPTY set means "All" (fetch every type). Toggling
// from empty therefore selects ONLY the clicked type, and completing the full set
// collapses back to All-mode so the chip state and the payload can never diverge.
export function toggleFetchType(
  selected: ReadonlySet<string>,
  key: string,
  all: readonly string[]
): Set<string> {
  const next = toggle(selected, key)
  return next.size === all.length ? new Set() : next
}

// Canonical-ordered reaction_types payload for POST /api/fetch, or null when no
// subset is active (= fetch all; the field is omitted from the request body).
export function fetchTypesPayload(
  selected: ReadonlySet<string>,
  all: readonly string[]
): string[] | null {
  if (selected.size === 0) return null
  return all.filter((t) => selected.has(t))
}

// Select all currently-visible keys (union with prior selection so a filtered
// "select all" never drops selections hidden by the active filter).
export function selectAll(selected: ReadonlySet<string>, visibleKeys: readonly string[]): Set<string> {
  const next = new Set(selected)
  for (const key of visibleKeys) next.add(key)
  return next
}

// Deselect only the currently-visible keys, leaving any hidden selections intact.
export function clearAll(selected: ReadonlySet<string>, visibleKeys: readonly string[]): Set<string> {
  const next = new Set(selected)
  for (const key of visibleKeys) next.delete(key)
  return next
}

// Profile URLs of the selected reactors, skipping any without a URL.
// De-duplicated, preserving reactor order.
export function selectedUrls(reactors: UIReactor[], selected: ReadonlySet<string>): string[] {
  const urls: string[] = []
  const seen = new Set<string>()
  for (const r of reactors) {
    if (!r.profile_url) continue
    if (!selected.has(r.profile_key)) continue
    if (seen.has(r.profile_url)) continue
    seen.add(r.profile_url)
    urls.push(r.profile_url)
  }
  return urls
}

// Count of selected reactors that have a usable profile URL (the number the block
// flow will actually act on).
export function selectedCount(reactors: UIReactor[], selected: ReadonlySet<string>): number {
  return selectedUrls(reactors, selected).length
}

// Distinct reaction types present, in first-seen order, for the filter chip row.
export function reactionTypes(reactors: UIReactor[]): string[] {
  const types: string[] = []
  const seen = new Set<string>()
  for (const r of reactors) {
    if (seen.has(r.reaction_type)) continue
    seen.add(r.reaction_type)
    types.push(r.reaction_type)
  }
  return types
}

// Per-reaction-type counts for the summary meter and filter-chip badges.
export function reactionCounts(reactors: UIReactor[]): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const r of reactors) {
    counts[r.reaction_type] = (counts[r.reaction_type] ?? 0) + 1
  }
  return counts
}
