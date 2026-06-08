from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

from reactions.config import ReactionConfig
from reactions.models import BlockOutcome, ReactorRecord
from reactions.service import FacebookBlocker
from reactions.storage import SQLiteStore

logger = logging.getLogger(__name__)

# Decision source for one target: returns the user's choice as a single char --
# "y" (act on this one), "n" (skip), "a" (yes to all; stop asking), or "q" (quit
# the run). Inject a custom confirmer to drive the orchestration non-interactively
# (tests, unattended batch); the default (:meth:`ProfileBlocker._prompt`) reads
# stdin.
Confirmer = Callable[[ReactorRecord, str], str]


class ProfileBlocker:
    """DB-driven orchestration over scraped reactors.

    Delegates the actual block/unblock UI work to :class:`FacebookBlocker` (the
    standalone by-URL service) and adds the database-aware concerns: dry-run
    preview, per-person confirmation, randomized delays, a daily cap, and marking
    rows blocked/unblocked. Nothing is blocked unless ``config.dry_run`` is False.
    """

    def __init__(self, config: ReactionConfig, store: SQLiteStore) -> None:
        self.config = config
        self.store = store

    # --- public API -------------------------------------------------------- #
    def preview(self, targets: list[ReactorRecord]) -> list[BlockOutcome]:
        """List who *would* be acted on without touching the browser."""
        return [
            BlockOutcome(
                profile_key=t.profile_key,
                name=t.name,
                profile_url=t.profile_url,
                status="dry_run",
                detail=t.reaction_type,
            )
            for t in targets
        ]

    def execute(
        self, targets: list[ReactorRecord], confirm: Confirmer | None = None
    ) -> list[BlockOutcome]:
        return self._run(targets, action="block", confirm=confirm)

    def execute_unblock(
        self, targets: list[ReactorRecord], confirm: Confirmer | None = None
    ) -> list[BlockOutcome]:
        return self._run(targets, action="unblock", confirm=confirm)

    # --- internals --------------------------------------------------------- #
    def _run(
        self,
        targets: list[ReactorRecord],
        action: str,
        confirm: Confirmer | None = None,
    ) -> list[BlockOutcome]:
        outcomes: list[BlockOutcome] = []
        is_block = action == "block"
        success = "blocked" if is_block else "unblocked"
        # Default to the interactive stdin prompt; callers/tests can inject their own.
        confirm = confirm or self._prompt

        # The daily cap guards the (anti-bot-sensitive) block action only, and only
        # when set: daily_cap <= 0 means unlimited (the default).
        cap = self.config.daily_cap
        if is_block and cap > 0:
            remaining = max(cap - self.store.count_blocked_today(), 0)
            if remaining <= 0:
                logger.warning("daily cap reached (%d); nothing to do", cap)
                print(f"Daily cap reached ({cap}). Nothing to do.")
                return outcomes
        else:
            remaining = len(targets)

        prompt_each = self.config.confirm_each
        with FacebookBlocker(
            self.config.profile_dir,
            headless=self.config.headless,
            dialog_timeout_ms=self.config.dialog_timeout_ms,
        ) as service:
            for target in targets:
                if is_block and cap > 0 and remaining <= 0:
                    logger.info("daily cap of %d reached; stopping", cap)
                    print(f"Daily cap of {cap} reached; stopping.")
                    break
                decision = confirm(target, action) if prompt_each else "y"
                if decision == "q":
                    break
                if decision == "a":
                    prompt_each = False
                elif decision == "n":
                    outcomes.append(self._outcome(target, "skipped", "user skipped"))
                    continue

                act = service.block if is_block else service.unblock
                outcome = act(target.profile_url, target.name)
                # Keep the DB dedup key + reaction type for display/marking.
                outcome.profile_key = target.profile_key
                outcome.detail = outcome.detail or target.reaction_type
                outcomes.append(outcome)

                if outcome.status == success:
                    mark = self.store.mark_blocked if is_block else self.store.mark_unblocked
                    mark(target.post_url, target.profile_key)
                    remaining -= 1
                    logger.info("%s %s", success, target.name or target.profile_key)
                    self._human_delay()
                else:
                    logger.warning(
                        "%s failed for %s: %s",
                        action,
                        target.name or target.profile_key,
                        outcome.detail,
                    )
        return outcomes

    def _prompt(self, target: ReactorRecord, action: str = "block") -> str:
        label = target.name or target.profile_url or target.profile_key
        answer = input(
            f"{action.capitalize()} {label} (reacted: {target.reaction_type})? "
            f"[y]es / [n]o / [a]ll / [q]uit: "
        ).strip().lower()
        return answer[:1] if answer else "n"

    def _human_delay(self) -> None:
        delay = random.uniform(self.config.block_min_delay_s, self.config.block_max_delay_s)
        time.sleep(delay)

    @staticmethod
    def _outcome(target: ReactorRecord, status: str, detail: str | None) -> BlockOutcome:
        return BlockOutcome(
            profile_key=target.profile_key,
            name=target.name,
            profile_url=target.profile_url,
            status=status,
            detail=detail,
        )
