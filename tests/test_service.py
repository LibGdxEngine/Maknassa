from __future__ import annotations

from pathlib import Path

import pytest

from reactions.config import ReactionConfig
from reactions.models import BlockOutcome
from reactions.service import FacebookBlocker, run_batch


def _url_config(daily_cap: int = 0) -> ReactionConfig:
    return ReactionConfig(
        post_url="",
        db_path=Path("unused.db"),
        profile_dir=Path("/tmp/unused"),
        # Zero delays keep the test fast (random.uniform(0, 0) == 0).
        block_min_delay_s=0.0,
        block_max_delay_s=0.0,
        daily_cap=daily_cap,
    )


def _ok(url: str) -> BlockOutcome:
    return BlockOutcome(profile_key="", name=None, profile_url=url, status="blocked")


def test_run_batch_unlimited_processes_all():
    """daily_cap <= 0 means unlimited: every URL is acted on."""
    calls: list[str] = []
    urls = [f"https://www.facebook.com/{i}" for i in range(4)]

    outcomes = run_batch(_url_config(daily_cap=0), lambda u: (calls.append(u), _ok(u))[1], urls)

    assert len(calls) == 4
    assert [o.status for o in outcomes] == ["blocked"] * 4


def test_run_batch_stops_at_cap():
    """A positive daily_cap stops the run after that many successful actions."""
    calls: list[str] = []
    urls = [f"https://www.facebook.com/{i}" for i in range(5)]

    outcomes = run_batch(_url_config(daily_cap=2), lambda u: (calls.append(u), _ok(u))[1], urls)

    assert len(calls) == 2
    assert [o.status for o in outcomes] == ["blocked", "blocked"]


def test_run_batch_cap_counts_only_successes():
    """Failed actions do not count toward the cap."""
    statuses = iter(["failed", "blocked", "failed", "blocked", "blocked"])

    def act(url: str) -> BlockOutcome:
        return BlockOutcome(profile_key="", name=None, profile_url=url, status=next(statuses))

    urls = [f"https://www.facebook.com/{i}" for i in range(5)]
    outcomes = run_batch(_url_config(daily_cap=2), act, urls)

    # Runs until 2 successes land (failed, blocked, failed, blocked), then stops.
    assert [o.status for o in outcomes] == ["failed", "blocked", "failed", "blocked"]


def test_block_requires_context_manager():
    """Calling block() without an active session fails fast (no browser launch)."""
    fb = FacebookBlocker(profile_dir="/tmp/does-not-matter", headless=True)
    with pytest.raises(RuntimeError):
        fb.block("https://www.facebook.com/someone")
    with pytest.raises(RuntimeError):
        fb.unblock("https://www.facebook.com/someone")


def test_profile_dir_is_resolved():
    fb = FacebookBlocker(profile_dir=".profiles/facebook", headless=True)
    assert fb.config.profile_dir.is_absolute()
    assert fb.page is None  # no session until __enter__
