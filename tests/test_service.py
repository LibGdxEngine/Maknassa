from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from reactions import service
from reactions.config import ReactionConfig
from reactions.models import BlockOutcome
from reactions.service import _BLOCK, _UNBLOCK, FacebookBlocker, menu_action, run_batch


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


# --------------------------------------------------------------------------- #
# menu_action: a successful Confirm click is the success signal; the post-confirm
# verification is advisory and must NEVER downgrade the status. menu_action's
# browser seams are module-level functions, so we monkeypatch reactions.service.*
# and drive the whole flow with a stub page -- no real browser.
# --------------------------------------------------------------------------- #
_URL = "https://www.facebook.com/someone"


def _patch_seams(monkeypatch, **overrides) -> None:
    seams = {
        "load_profile": lambda *a, **k: None,
        "open_more_menu": lambda *a, **k: True,
        "native_click_by_name": lambda *a, **k: True,
        "click_confirm": lambda *a, **k: True,
        "wait_for_confirm_dialog_closed": lambda *a, **k: True,
        "verify": lambda *a, **k: True,
        **overrides,
    }
    for name, fn in seams.items():
        monkeypatch.setattr(service, name, fn)


def test_menu_action_success_when_dialog_closes(monkeypatch):
    _patch_seams(monkeypatch, wait_for_confirm_dialog_closed=lambda *a, **k: True)
    outcome = menu_action(_url_config(), object(), _URL, None, **_BLOCK)
    assert outcome.status == "blocked"
    assert outcome.detail is None


def test_menu_action_success_even_when_close_check_times_out(monkeypatch):
    """The reported bug: confirm clicked but the close/verify check times out.

    A blocked profile is immediately inaccessible, so the check can't observe the
    closed dialog -- but the block succeeded. Status must stay "blocked", clean.
    """
    _patch_seams(monkeypatch, wait_for_confirm_dialog_closed=lambda *a, **k: False)
    outcome = menu_action(_url_config(), object(), _URL, None, **_BLOCK)
    assert outcome.status == "blocked"
    assert outcome.detail is None


def test_menu_action_unblock_success_on_confirm(monkeypatch):
    _patch_seams(monkeypatch, wait_for_confirm_dialog_closed=lambda *a, **k: False)
    outcome = menu_action(_url_config(), object(), _URL, None, **_UNBLOCK)
    assert outcome.status == "unblocked"
    assert outcome.detail is None


def test_menu_action_verify_reload_is_advisory(monkeypatch):
    """With verify_reload on, a failing reload-based verify must not fail the block."""
    config = _url_config()
    config.verify_reload = True
    _patch_seams(monkeypatch, verify=lambda *a, **k: False)
    outcome = menu_action(config, object(), _URL, None, **_BLOCK)
    assert outcome.status == "blocked"
    assert outcome.detail is None


@pytest.mark.parametrize(
    "overrides, expected_detail",
    [
        ({"open_more_menu": lambda *a, **k: False}, "profile actions menu not found"),
        ({"native_click_by_name": lambda *a, **k: False}, "block menu item not found"),
        ({"click_confirm": lambda *a, **k: False}, "Confirm button not found"),
    ],
)
def test_menu_action_failed_paths_intact(monkeypatch, overrides, expected_detail):
    """Genuine failures still return status 'failed' with their specific detail."""
    _patch_seams(monkeypatch, **overrides)
    outcome = menu_action(_url_config(), object(), _URL, None, **_BLOCK)
    assert outcome.status == "failed"
    assert outcome.detail == expected_detail


def test_menu_action_timeout_is_failed(monkeypatch):
    def boom(*a, **k):
        raise PlaywrightTimeoutError("navigation timed out")

    _patch_seams(monkeypatch, load_profile=boom)
    outcome = menu_action(_url_config(), object(), _URL, None, **_BLOCK)
    assert outcome.status == "failed"
    assert outcome.detail is not None and outcome.detail.startswith("timeout:")


def test_menu_action_no_url_is_failed():
    outcome = menu_action(_url_config(), object(), "", None, **_BLOCK)
    assert outcome.status == "failed"
    assert outcome.detail == "no profile url"


# --------------------------------------------------------------------------- #
# Static guards on the menu-open JS: the early-exit poll replaced the fixed 1.2s
# wait, the post-menu ranking is present, and the candidate filter stays identical
# to the readiness check (load_profile waits on the SAME element the opener needs).
# --------------------------------------------------------------------------- #
_IS_CANDIDATE_SNIPPET = """const isCandidate = (el) => {
    const a = lc(el.getAttribute('aria-label'));
    const t = lc(el.innerText);
    if (distractors.some((d) => d && (a.includes(d) || t.includes(d)))) return false;
    return labels.some((l) => l && (a === l || t === l || a.includes(l) || t.includes(l)));
  };"""


def test_open_actions_script_uses_early_exit_poll():
    script = service._OPEN_ACTIONS_MENU_SCRIPT
    assert "await sleep(1200)" not in script  # the flat wait is gone
    assert "menuHasMarker()" in script
    assert 'role="article"' in script  # post menus ranked last


def test_candidate_filter_consistent_between_scripts():
    assert _IS_CANDIDATE_SNIPPET in service._OPEN_ACTIONS_MENU_SCRIPT
    assert _IS_CANDIDATE_SNIPPET in service._ACTION_BAR_READY_SCRIPT
