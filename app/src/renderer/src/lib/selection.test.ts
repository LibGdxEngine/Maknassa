import { describe, expect, it } from 'vitest'
import {
  clearAll,
  filteredKeys,
  reactionCounts,
  reactionTypes,
  selectAll,
  selectedCount,
  selectedUrls,
  toggle
} from './selection'
import type { UIReactor } from './types'

function reactor(key: string, type: string, url: string | null = `https://fb/${key}`): UIReactor {
  return {
    name: `Name ${key}`,
    profile_url: url,
    profile_key: key,
    reaction_type: type,
    avatar_url: null
  }
}

const reactors: UIReactor[] = [
  reactor('a', 'like'),
  reactor('b', 'love'),
  reactor('c', 'like'),
  reactor('d', 'wow', null) // no profile_url
]

describe('toggle', () => {
  it('adds a missing key and removes a present one', () => {
    const once = toggle(new Set<string>(), 'a')
    expect([...once]).toEqual(['a'])
    const twice = toggle(once, 'a')
    expect([...twice]).toEqual([])
  })

  it('does not mutate the input set', () => {
    const input = new Set(['a'])
    toggle(input, 'b')
    expect([...input]).toEqual(['a'])
  })
})

describe('filteredKeys', () => {
  it('returns every key when no filter is active', () => {
    expect(filteredKeys(reactors, new Set())).toEqual(['a', 'b', 'c', 'd'])
  })

  it('narrows to keys matching the active reaction types', () => {
    expect(filteredKeys(reactors, new Set(['like']))).toEqual(['a', 'c'])
  })
})

describe('selectAll / clearAll', () => {
  it('selectAll unions visible keys with prior selection', () => {
    const next = selectAll(new Set(['z']), ['a', 'c'])
    expect([...next].sort()).toEqual(['a', 'c', 'z'])
  })

  it('clearAll removes only the visible keys', () => {
    const next = clearAll(new Set(['a', 'c', 'z']), ['a', 'c'])
    expect([...next]).toEqual(['z'])
  })
})

describe('selectedUrls / selectedCount', () => {
  it('skips reactors without a profile_url', () => {
    const selected = new Set(['a', 'd'])
    expect(selectedUrls(reactors, selected)).toEqual(['https://fb/a'])
    expect(selectedCount(reactors, selected)).toBe(1)
  })

  it('preserves reactor order and de-duplicates urls', () => {
    const dup = [...reactors, reactor('e', 'like', 'https://fb/a')]
    const selected = new Set(['a', 'c', 'e'])
    expect(selectedUrls(dup, selected)).toEqual(['https://fb/a', 'https://fb/c'])
  })
})

describe('reactionTypes / reactionCounts', () => {
  it('lists distinct types in first-seen order', () => {
    expect(reactionTypes(reactors)).toEqual(['like', 'love', 'wow'])
  })

  it('counts reactors per type', () => {
    expect(reactionCounts(reactors)).toEqual({ like: 2, love: 1, wow: 1 })
  })
})
