// Persistent "who have I already blocked" memory, keyed by profile_key and kept in
// localStorage so it survives across fetches and app restarts. The desktop flow never
// touched the backend's reactions.db, so this is the lightest place to remember blocks:
// on re-fetching any post, previously-blocked reactors are badged and can be hidden,
// sparing a redundant browser navigation, a randomized delay, and daily-cap budget.
//
// The block path returns the same profile_key the grid derived for a reactor (the UI
// sends the already-normalized profile_url and the backend re-normalizes idempotently),
// so badges line up by key. The pure merge/remove folds are unit-tested; the
// localStorage load/save are thin best-effort I/O.

import type { BlockOutcome } from './types'

export interface BlockRecord {
  name: string | null
  url: string | null
  blockedAt: string // ISO timestamp
}

export type Blocklist = Record<string, BlockRecord>

const STORAGE_KEY = 'maknassa.blocklist.v1'

// Pure: fold the 'blocked' outcomes of a run into the map (keyed by profile_key).
// Non-blocked outcomes (failed/skipped/dry_run/unblocked) are ignored. `now` is
// injected rather than read from the clock so the fold stays deterministic in tests.
export function mergeBlocked(current: Blocklist, outcomes: BlockOutcome[], now: string): Blocklist {
  const next = { ...current }
  for (const o of outcomes) {
    if (o.status !== 'blocked') continue
    next[o.profile_key] = { name: o.name, url: o.profile_url, blockedAt: now }
  }
  return next
}

// Pure: drop one entry by profile_key (e.g. after a successful unblock). Returns the
// same reference when the key is absent so callers can skip a needless state update.
export function removeBlocked(current: Blocklist, key: string): Blocklist {
  if (!(key in current)) return current
  const next = { ...current }
  delete next[key]
  return next
}

export function loadBlocklist(): Blocklist {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed: unknown = JSON.parse(raw)
    // Accept only a plain object map; a JSON array also satisfies `typeof 'object'`
    // but its numeric indices would never match a profile_key.
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Blocklist)
      : {}
  } catch {
    return {} // corrupt/unavailable storage -> start empty rather than crash
  }
}

export function saveBlocklist(list: Blocklist): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list))
  } catch {
    // Storage full or unavailable: the in-memory state still works for this session.
  }
}
