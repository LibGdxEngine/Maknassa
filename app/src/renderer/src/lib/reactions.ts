// Reaction-type -> emoji badges shown beside each reactor.

// Canonical reaction keys a fetch can be narrowed to, mirroring the backend's
// REACTION_LABELS order (reactions/selectors.py).
export const REACTION_TYPES = ['like', 'love', 'care', 'haha', 'wow', 'sad', 'angry'] as const

const FALLBACK_EMOJI = '⚪'

const REACTION_EMOJI: Record<string, string> = {
  like: '👍',
  love: '❤️',
  care: '🤗',
  haha: '😆',
  wow: '😮',
  sad: '😢',
  angry: '😡',
  all: '🔘',
  unknown: FALLBACK_EMOJI
}

export function reactionEmoji(reactionType: string): string {
  return REACTION_EMOJI[reactionType] ?? FALLBACK_EMOJI
}

// Icon per BlockOutcome.status: success, preview, skip, or failure.
export function outcomeIcon(status: string): string {
  if (status === 'blocked' || status === 'unblocked') return '✅'
  if (status === 'dry_run') return '👁️'
  if (status === 'skipped') return '⏭️'
  return '❌'
}
