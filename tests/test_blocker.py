"""Unit tests for ProfileBlocker orchestration.

Driving _run with an injected confirmer (instead of stdin) and a fake by-URL
service + fake store lets us cover the decision handling (y/n/a/q), the daily
cap, and DB marking with no browser and no real database.
"""

from __future__ import annotations

from pathlib import Path

import reactions.blocker as blocker_mod
from reactions.blocker import ProfileBlocker
from reactions.config import ReactionConfig
from reactions.models import BlockOutcome, ReactorRecord

POST_URL = "https://www.facebook.com/some.page/posts/1"


# --- fakes ----------------------------------------------------------------- #
class _FakeService:
    """Stand-in for FacebookBlocker: records calls, returns canned outcomes."""

    def __init__(self, status: str = "blocked") -> None:
        self.status = status
        self.calls: list[tuple[str, str | None]] = []

    def block(self, url: str, name: str | None = None) -> BlockOutcome:
        self.calls.append((url, name))
        return BlockOutcome(profile_key="", name=name, profile_url=url, status=self.status)

    def unblock(self, url: str, name: str | None = None) -> BlockOutcome:
        self.calls.append((url, name))
        status = "unblocked" if self.status == "blocked" else self.status
        return BlockOutcome(profile_key="", name=name, profile_url=url, status=status)


class _FakeServiceCtx:
    def __init__(self, service: _FakeService) -> None:
        self.service = service

    def __enter__(self) -> _FakeService:
        return self.service

    def __exit__(self, *_exc) -> bool:
        return False


class _FakeStore:
    def __init__(self, blocked_today: int = 0) -> None:
        self._blocked_today = blocked_today
        self.marked_blocked: list[tuple[str, str]] = []
        self.marked_unblocked: list[tuple[str, str]] = []

    def count_blocked_today(self) -> int:
        return self._blocked_today

    def mark_blocked(self, post_url: str, profile_key: str) -> None:
        self.marked_blocked.append((post_url, profile_key))

    def mark_unblocked(self, post_url: str, profile_key: str) -> None:
        self.marked_unblocked.append((post_url, profile_key))


# --- helpers --------------------------------------------------------------- #
def _config(**overrides) -> ReactionConfig:
    base = dict(
        post_url=POST_URL,
        db_path=Path("unused.db"),
        profile_dir=Path("/tmp/unused"),
        # Zero delays keep the test fast (random.uniform(0, 0) == 0).
        block_min_delay_s=0.0,
        block_max_delay_s=0.0,
    )
    base.update(overrides)
    return ReactionConfig(**base)


def _target(key: str, name: str, reaction: str = "angry") -> ReactorRecord:
    return ReactorRecord(
        profile_id=key,
        profile_key=key,
        name=name,
        profile_url=f"https://www.facebook.com/{key}",
        reaction_type=reaction,
        post_url=POST_URL,
    )


def _scripted_confirmer(decisions):
    it = iter(decisions)
    calls: list[tuple[str, str]] = []

    def confirm(target: ReactorRecord, action: str) -> str:
        calls.append((target.profile_key, action))
        return next(it)

    confirm.calls = calls  # type: ignore[attr-defined]
    return confirm


def _patch_service(monkeypatch, service: _FakeService) -> None:
    monkeypatch.setattr(blocker_mod, "FacebookBlocker", lambda *a, **k: _FakeServiceCtx(service))


# --- tests ----------------------------------------------------------------- #
def test_block_marks_db_and_calls_service(monkeypatch):
    service = _FakeService(status="blocked")
    _patch_service(monkeypatch, service)
    store = _FakeStore()
    blocker = ProfileBlocker(_config(), store)

    outcomes = blocker.execute([_target("1", "Ann")], confirm=_scripted_confirmer(["y"]))

    assert [o.status for o in outcomes] == ["blocked"]
    assert service.calls == [("https://www.facebook.com/1", "Ann")]
    assert store.marked_blocked == [(POST_URL, "1")]


def test_no_skips_target_without_calling_service(monkeypatch):
    service = _FakeService()
    _patch_service(monkeypatch, service)
    store = _FakeStore()
    blocker = ProfileBlocker(_config(), store)

    outcomes = blocker.execute([_target("1", "Ann")], confirm=_scripted_confirmer(["n"]))

    assert [o.status for o in outcomes] == ["skipped"]
    assert service.calls == []
    assert store.marked_blocked == []


def test_quit_stops_the_run(monkeypatch):
    service = _FakeService()
    _patch_service(monkeypatch, service)
    blocker = ProfileBlocker(_config(), _FakeStore())

    confirm = _scripted_confirmer(["q"])
    outcomes = blocker.execute([_target("1", "Ann"), _target("2", "Bob")], confirm=confirm)

    assert outcomes == []
    assert service.calls == []
    assert confirm.calls == [("1", "block")]  # asked once, then quit


def test_all_decision_stops_prompting(monkeypatch):
    service = _FakeService(status="blocked")
    _patch_service(monkeypatch, service)
    store = _FakeStore()
    blocker = ProfileBlocker(_config(), store)

    confirm = _scripted_confirmer(["a"])  # one decision drives all remaining targets
    outcomes = blocker.execute(
        [_target("1", "Ann"), _target("2", "Bob")], confirm=confirm
    )

    assert [o.status for o in outcomes] == ["blocked", "blocked"]
    assert len(service.calls) == 2
    assert confirm.calls == [("1", "block")]  # only the first target was prompted


def test_daily_cap_blocks_nothing(monkeypatch):
    service = _FakeService()
    _patch_service(monkeypatch, service)
    store = _FakeStore(blocked_today=50)
    blocker = ProfileBlocker(_config(daily_cap=50), store)

    outcomes = blocker.execute([_target("1", "Ann")], confirm=_scripted_confirmer(["y"]))

    assert outcomes == []
    assert service.calls == []


def test_failed_block_is_not_marked(monkeypatch):
    service = _FakeService(status="failed")
    _patch_service(monkeypatch, service)
    store = _FakeStore()
    blocker = ProfileBlocker(_config(), store)

    outcomes = blocker.execute([_target("1", "Ann")], confirm=_scripted_confirmer(["y"]))

    assert [o.status for o in outcomes] == ["failed"]
    assert store.marked_blocked == []


def test_confirm_each_false_blocks_without_prompting(monkeypatch):
    service = _FakeService(status="blocked")
    _patch_service(monkeypatch, service)
    store = _FakeStore()
    blocker = ProfileBlocker(_config(confirm_each=False), store)

    # No confirmer passed; confirm_each=False must short-circuit to "yes".
    outcomes = blocker.execute([_target("1", "Ann")])

    assert [o.status for o in outcomes] == ["blocked"]
    assert store.marked_blocked == [(POST_URL, "1")]
