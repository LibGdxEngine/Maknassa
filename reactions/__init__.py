"""Facebook reaction scraper + selective blocker.

Given a single Facebook post URL, collect everyone who reacted (per reaction
type) and optionally block a reaction category or hand-picked people.

All Facebook DOM selection lives in :mod:`reactions.selectors` and is matched on
stable semantic signals (href shape, ARIA role, aria-label, localized text) --
never on Facebook's randomized CSS class names.
"""
