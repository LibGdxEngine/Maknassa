from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, replace
from functools import reduce
from typing import Callable

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


@dataclass(frozen=True)
class _RunState:
    """Immutable control state threaded through the block/unblock fold.

    ``reduce`` can't ``break``, so early exit (quit / daily cap) is carried as the
    ``stopped`` flag: once set, the reducer passes the state through untouched.
    Outcomes are accumulated in a plain list outside the fold -- appending is a
    side effect anyway, and it keeps accumulation O(n) instead of the O(n^2) of
    rebuilding an immutable tuple each step.
    """

    remaining: int = 0
    prompt_each: bool = True
    stopped: bool = False


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
        is_block = action == "block"
        success = "blocked" if is_block else "unblocked"
        # Default to the interactive stdin prompt; callers/tests can inject their own.
        confirm = confirm or self._prompt

        # The daily cap guards the (anti-bot-sensitive) block action only.
        if is_block:
            start_remaining = max(self.config.daily_cap - self.store.count_blocked_today(), 0)
            if start_remaining <= 0:
                logger.warning("daily cap reached (%d); nothing to do", self.config.daily_cap)
                print(f"Daily cap reached ({self.config.daily_cap}). Nothing to do.")
                return []
        else:
            start_remaining = len(targets)

        outcomes: list[BlockOutcome] = []
        with FacebookBlocker(
            self.config.profile_dir,
            headless=self.config.headless,
            dialog_timeout_ms=self.config.dialog_timeout_ms,
        ) as service:

            def step(state: _RunState, target: ReactorRecord) -> _RunState:
                # NOTE (spike): a fold over effectful, early-terminating work is
                # noticeably more contorted than the imperative loop it replaces --
                # the control state threads immutably, `stopped` fakes the `break`
                # that `reduce` lacks, and outcomes accumulate via an external list
                # (appending is a side effect either way). This is the honest cost.
                if state.stopped:
                    return state
                if is_block and state.remaining <= 0:
                    logger.info("daily cap of %d reached; stopping", self.config.daily_cap)
                    print(f"Daily cap of {self.config.daily_cap} reached; stopping.")
                    return replace(state, stopped=True)

                decision = confirm(target, action) if state.prompt_each else "y"
                if decision == "q":
                    return replace(state, stopped=True)
                prompt_each = False if decision == "a" else state.prompt_each
                if decision == "n":
                    outcomes.append(self._outcome(target, "skipped", "user skipped"))
                    return replace(state, prompt_each=prompt_each)

                act = service.block if is_block else service.unblock
                outcome = act(target.profile_url, target.name)
                # Keep the DB dedup key + reaction type for display/marking.
                outcome.profile_key = target.profile_key
                outcome.detail = outcome.detail or target.reaction_type
                outcomes.append(outcome)

                if outcome.status != success:
                    logger.warning(
                        "%s failed for %s: %s",
                        action,
                        target.name or target.profile_key,
                        outcome.detail,
                    )
                    return replace(state, prompt_each=prompt_each)

                mark = self.store.mark_blocked if is_block else self.store.mark_unblocked
                mark(target.post_url, target.profile_key)
                logger.info("%s %s", success, target.name or target.profile_key)
                self._human_delay()
                return replace(state, remaining=state.remaining - 1, prompt_each=prompt_each)

            reduce(
                step,
                targets,
                _RunState(remaining=start_remaining, prompt_each=self.config.confirm_each),
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
