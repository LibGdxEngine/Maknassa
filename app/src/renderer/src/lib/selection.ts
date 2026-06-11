// Pure selection logic for the reactor grid. Components stay thin by delegating all
// set math here; vitest covers these directly. Selection is keyed by profile_key.

import type { UIReactor } from './types'

// Profile keys currently visible under the active reaction-type filters. An empty
// filter set means "no filter" -> every reactor is visible (mirrors the Streamlit
// grid showing all reactors with no per-type narrowing).
export function filteredKeys(reactors: UIReactor[], activeTypes: ReadonlySet<string>): string[] {
  if (activeTypes.size === 0) return reactors.map((r) => r.profile_key)
  return reactors.filter((r) => activeTypes.has(r.reaction_type)).map((r) => r.profile_key)
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

// Profile URLs of the selected reactors, skipping any without a URL (matches
// streamlit_app._selected_urls). De-duplicated, preserving reactor order.
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
