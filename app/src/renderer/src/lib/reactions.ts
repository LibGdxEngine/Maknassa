// Reaction-type -> emoji mapping, mirrored from streamlit_app.py REACTION_EMOJI so
// the desktop UI shows the same badges users already know.

export const REACTION_EMOJI: Record<string, string> = {
  like: '👍',
  love: '❤️',
  care: '🤗',
  haha: '😆',
  wow: '😮',
  sad: '😢',
  angry: '😡',
  all: '🔘',
  unknown: '⚪'
}

const FALLBACK_EMOJI = '⚪'

export function reactionEmoji(reactionType: string): string {
  return REACTION_EMOJI[reactionType] ?? FALLBACK_EMOJI
}

// Icon per BlockOutcome.status, matching streamlit_app._render_outcomes (blocked -> ✅,
// anything else -> ❌) and the unblock success path.
export function outcomeIcon(status: string): string {
  if (status === 'blocked' || status === 'unblocked') return '✅'
  return '❌'
}
