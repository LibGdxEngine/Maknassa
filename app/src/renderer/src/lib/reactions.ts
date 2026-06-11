// Reaction-type -> emoji badges shown beside each reactor.

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

// Icon per BlockOutcome.status: a success (blocked / unblocked) vs anything else.
export function outcomeIcon(status: string): string {
  if (status === 'blocked' || status === 'unblocked') return '✅'
  return '❌'
}
