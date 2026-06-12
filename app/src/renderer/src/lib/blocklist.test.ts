import { describe, expect, it } from 'vitest'
import { mergeBlocked, removeBlocked, type Blocklist } from './blocklist'
import type { BlockOutcome } from './types'

function outcome(key: string, status: string): BlockOutcome {
  return {
    profile_key: key,
    name: `Name ${key}`,
    profile_url: `https://fb/${key}`,
    status,
    detail: null
  }
}

const NOW = '2026-06-12T00:00:00.000Z'

describe('mergeBlocked', () => {
  it('adds only blocked outcomes, keyed by profile_key', () => {
    const next = mergeBlocked({}, [outcome('a', 'blocked'), outcome('b', 'failed')], NOW)
    expect(Object.keys(next)).toEqual(['a'])
    expect(next.a).toEqual({ name: 'Name a', url: 'https://fb/a', blockedAt: NOW })
  })

  it('ignores non-blocked statuses (failed/skipped/dry_run/unblocked)', () => {
    const outcomes = ['failed', 'skipped', 'dry_run', 'unblocked'].map((s) => outcome('x', s))
    expect(mergeBlocked({}, outcomes, NOW)).toEqual({})
  })

  it('merges into existing entries without dropping them', () => {
    const prev: Blocklist = { a: { name: 'A', url: 'u', blockedAt: 'earlier' } }
    const next = mergeBlocked(prev, [outcome('b', 'blocked')], NOW)
    expect(Object.keys(next).sort()).toEqual(['a', 'b'])
    expect(next.a).toBe(prev.a) // untouched entry kept by reference
  })

  it('does not mutate the input map', () => {
    const prev: Blocklist = {}
    mergeBlocked(prev, [outcome('a', 'blocked')], NOW)
    expect(prev).toEqual({})
  })
})

describe('removeBlocked', () => {
  it('drops the named key', () => {
    const prev: Blocklist = { a: { name: null, url: null, blockedAt: NOW } }
    expect(removeBlocked(prev, 'a')).toEqual({})
  })

  it('returns the same reference when the key is absent', () => {
    const prev: Blocklist = { a: { name: null, url: null, blockedAt: NOW } }
    expect(removeBlocked(prev, 'missing')).toBe(prev)
  })

  it('does not mutate the input map', () => {
    const prev: Blocklist = { a: { name: null, url: null, blockedAt: NOW } }
    removeBlocked(prev, 'a')
    expect(Object.keys(prev)).toEqual(['a'])
  })
})
