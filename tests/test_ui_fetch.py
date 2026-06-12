"""Unit tests for the Streamlit UI fetch seam (reactions.ui_fetch).

These exercise the pure normalization/dedup/merge logic and the tab-walking
orchestration with a stubbed Playwright page -- no live browser, no database,
mirroring tests/test_browser_collect.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reactions import ui_fetch
from reactions.config import ReactionConfig
from reactions.selectors import REACTION_LABELS
from reactions.ui_fetch import (
    build_ui_reactors,
    fetch_with_page,
    in_thread,
    merge_reactors,
)

POST_URL = "https://www.facebook.com/some.page/posts/123456789"

AVATAR_A = "https://scontent.fcdn.net/a.jpg"
AVATAR_J = "https://scontent.fcdn.net/j.jpg"


# --------------------------------------------------------------------------- #
# build_ui_reactors: normalize + dedup + reject + carry avatar
# --------------------------------------------------------------------------- #
def test_build_ui_reactors_normalizes_dedups_rejects_and_keeps_avatar():
    rows = [
        {
            "name": "Ahmed",
            "profile_url": "https://www.facebook.com/profile.php?id=100012345&__tn__=R",
            "avatar_url": AVATAR_A,
        },
        # Same numeric id (tracking stripped) -> de-duplicated away (first wins).
        {
            "name": "Ahmed again",
            "profile_url": "https://www.facebook.com/profile.php?id=100012345",
            "avatar_url": "https://scontent.fcdn.net/other.jpg",
        },
        {"name": "John", "profile_url": "https://www.facebook.com/john.doe.5", "avatar_url": AVATAR_J},
        # Non-profile links are rejected by parse_reactor.
        {"name": "A Group", "profile_url": "https://www.facebook.com/groups/999", "avatar_url": None},
        {"name": "No URL", "profile_url": None, "avatar_url": None},
    ]
    reactors = build_ui_reactors(POST_URL, "angry", "en", rows)

    assert [r.profile_key for r in reactors] == ["100012345", "john.doe.5"]
    assert all(r.reaction_type == "angry" for r in reactors)
    by_key = {r.profile_key: r for r in reactors}
    assert by_key["100012345"].avatar_url == AVATAR_A  # first occurrence's avatar kept
    assert by_key["100012345"].name == "Ahmed"
    assert by_key["john.doe.5"].avatar_url == AVATAR_J


def test_build_ui_reactors_tolerates_missing_avatar_key():
    rows = [{"name": "John", "profile_url": "https://www.facebook.com/john.doe.5"}]
    reactors = build_ui_reactors(POST_URL, "like", "en", rows)
    assert reactors[0].avatar_url is None
    assert reactors[0].reaction_type == "like"


def test_build_ui_reactors_captures_group_member_links():
    """Group-post reactors (/groups/<gid>/user/<uid>/) must be captured, not dropped,
    with their avatar and a canonical, blockable profile URL.
    """
    rows = [
        {
            "name": "Sara",
            "profile_url": "https://www.facebook.com/groups/123/user/456/",
            "avatar_url": AVATAR_A,
        },
        {
            "name": "Karim",
            "profile_url": "https://www.facebook.com/groups/123/user/789/",
            "avatar_url": AVATAR_J,
        },
        # Same group member again -> de-duplicated away.
        {
            "name": "Sara dup",
            "profile_url": "https://www.facebook.com/groups/123/user/456/",
            "avatar_url": None,
        },
    ]
    reactors = build_ui_reactors(POST_URL, "love", "en", rows)

    assert [r.profile_key for r in reactors] == ["456", "789"]
    by_key = {r.profile_key: r for r in reactors}
    assert by_key["456"].profile_url == "https://www.facebook.com/profile.php?id=456"
    assert by_key["456"].avatar_url == AVATAR_A
    assert by_key["456"].name == "Sara"
    assert all(r.reaction_type == "love" for r in reactors)


# --------------------------------------------------------------------------- #
# merge_reactors: cross-tab dedup + avatar backfill
# --------------------------------------------------------------------------- #
def test_merge_reactors_dedups_across_tabs_first_type_wins():
    love = build_ui_reactors(
        POST_URL, "love", "en",
        [{"name": "John", "profile_url": "https://www.facebook.com/john.doe.5", "avatar_url": AVATAR_J}],
    )
    # Same person shows up again under the 'all' tab; love must win, not 'all'.
    all_tab = build_ui_reactors(
        POST_URL, "all", "en",
        [
            {"name": "John", "profile_url": "https://www.facebook.com/john.doe.5", "avatar_url": AVATAR_J},
            {"name": "Sara", "profile_url": "https://www.facebook.com/sara.x", "avatar_url": None},
        ],
    )
    merged = merge_reactors([love, all_tab])
    by_key = {r.profile_key: r for r in merged}
    assert set(by_key) == {"john.doe.5", "sara.x"}
    assert by_key["john.doe.5"].reaction_type == "love"  # first tab wins the type


def test_merge_reactors_backfills_missing_avatar_from_later_tab():
    first = build_ui_reactors(
        POST_URL, "haha", "en",
        [{"name": "Sara", "profile_url": "https://www.facebook.com/sara.x"}],  # no avatar
    )
    later = build_ui_reactors(
        POST_URL, "all", "en",
        [{"name": "Sara", "profile_url": "https://www.facebook.com/sara.x", "avatar_url": AVATAR_A}],
    )
    merged = merge_reactors([first, later])
    assert len(merged) == 1
    assert merged[0].reaction_type == "haha"  # type still from the first tab
    assert merged[0].avatar_url == AVATAR_A  # avatar backfilled from the later tab


# --------------------------------------------------------------------------- #
# in_thread: result + exception propagation
# --------------------------------------------------------------------------- #
def test_in_thread_returns_result_and_forwards_args():
    assert in_thread(lambda a, b: a + b, 2, 3) == 5
    assert in_thread(lambda x, y=0: x * y, 4, y=5) == 20


def test_in_thread_propagates_exceptions():
    def boom() -> None:
        raise ValueError("kaboom")

    with pytest.raises(ValueError, match="kaboom"):
        in_thread(boom)


def test_in_thread_runs_on_a_different_thread():
    import threading

    here = threading.current_thread().name
    where = in_thread(lambda: threading.current_thread().name)
    assert where != here


# --------------------------------------------------------------------------- #
# fetch_with_page: tab-walking orchestration against a stub page
# --------------------------------------------------------------------------- #
class _StubLocator:
    def __init__(self, lang: str | None) -> None:
        self._lang = lang

    def get_attribute(self, _name: str) -> str | None:
        return self._lang


class _StubPage:
    """Dispatches page.evaluate by the script constant it is handed.

    Models a 2-tab dialog (Love, Haha). Clicking a tab updates which row set the
    avatar collector returns next, so fetch_with_page tags each reactor with the
    right reaction type.
    """

    def __init__(self, rows_by_index: dict[int, list[dict]], lang: str = "en") -> None:
        self._rows_by_index = rows_by_index
        self._lang = lang
        self._active = 0
        self.clicks: list[int] = []  # tab indices activated, in order

    def evaluate(self, script, arg=None):
        from reactions import browser

        if "summaryPatterns" in str(arg or ""):  # OPEN_REACTIONS_SCRIPT payload
            return "summary:5"
        if script is ui_fetch.ENUM_TABS_SCRIPT:
            return [
                {"index": 0, "aria": "Love", "text": "Love 1", "alts": []},
                {"index": 1, "aria": "Haha", "text": "Haha 1", "alts": []},
            ]
        if script is browser.OPEN_MORE_MENU_SCRIPT:
            return False  # no "More" overflow in the stub: every tab is directly clickable
        if script is browser.CLICK_OVERFLOW_ITEM_SCRIPT:
            return False
        if script is browser.CLICK_TAB_SCRIPT:
            self._active = arg
            self.clicks.append(arg)
            return True
        if script is browser.TAB_SELECTED_SCRIPT:
            return arg == self._active
        if script is ui_fetch.COLLECT_TAB_WITH_AVATARS_SCRIPT:
            return self._rows_by_index.get(self._active, [])
        raise AssertionError(f"unexpected script: {script!r}")

    keyboard = type("_K", (), {"press": staticmethod(lambda _key: None)})()

    def wait_for_selector(self, _selector: str, timeout: int | None = None):
        return None

    def wait_for_function(self, _expression: str, timeout: int | None = None):
        return None

    def wait_for_timeout(self, _ms: int) -> None:
        return None

    def locator(self, _selector: str) -> _StubLocator:
        return _StubLocator(self._lang)


def _config(reaction_types: tuple[str, ...] | None = None) -> ReactionConfig:
    return ReactionConfig(
        post_url=POST_URL,
        db_path=Path("unused.db"),
        profile_dir=Path("/tmp/unused"),
        reaction_types=reaction_types,
    )


def test_fetch_with_page_walks_tabs_and_tags_reaction_types():
    # open_reactions_dialog calls OPEN_REACTIONS_SCRIPT then wait_for_selector; the
    # stub returns a truthy strategy for the OPEN payload, so the dialog "opens".
    rows_by_index = {
        0: [{"name": "John", "profile_url": "https://www.facebook.com/john.doe.5", "avatar_url": AVATAR_J}],
        1: [{"name": "Sara", "profile_url": "https://www.facebook.com/sara.x", "avatar_url": AVATAR_A}],
    }
    result = fetch_with_page(_StubPage(rows_by_index), _config())
    by_key = {r.profile_key: r for r in result.reactors}
    assert set(by_key) == {"john.doe.5", "sara.x"}
    assert by_key["john.doe.5"].reaction_type == "love"
    assert by_key["sara.x"].reaction_type == "haha"
    assert by_key["sara.x"].avatar_url == AVATAR_A
    # expected_total = max(sum of per-type badges 1+1, summary count from "summary:5")
    # -> the opener's count wins as the completeness target.
    assert result.expected_total == 5


def test_fetch_with_page_filters_tabs_and_meters_selected_badges_only():
    rows_by_index = {
        0: [{"name": "John", "profile_url": "https://www.facebook.com/john.doe.5", "avatar_url": AVATAR_J}],
        1: [{"name": "Sara", "profile_url": "https://www.facebook.com/sara.x", "avatar_url": AVATAR_A}],
    }
    page = _StubPage(rows_by_index)
    result = fetch_with_page(page, _config(reaction_types=("haha",)))
    assert [r.profile_key for r in result.reactors] == ["sara.x"]
    assert page.clicks == [1]  # the Love tab is never activated, let alone scrolled
    # Metered against the selected tab's badge (Haha 1), NOT the whole-post summary
    # (5) -- a deliberately partial fetch must not read as a shortfall.
    assert result.expected_total == 1


def test_fetch_with_page_filter_zero_match_is_empty_result():
    page = _StubPage({})
    result = fetch_with_page(page, _config(reaction_types=("angry",)))
    assert result.reactors == []
    assert result.expected_total == 0
    assert page.clicks == []  # neither tab activated


def test_fetch_with_page_streams_progress_per_tab():
    rows_by_index = {
        0: [{"name": "John", "profile_url": "https://www.facebook.com/john.doe.5", "avatar_url": AVATAR_J}],
        1: [{"name": "Sara", "profile_url": "https://www.facebook.com/sara.x", "avatar_url": AVATAR_A}],
    }
    updates: list[dict] = []
    result = fetch_with_page(_StubPage(rows_by_index), _config(), updates.append)
    # One emit before the first tab (done=0), then one per tab with a cumulative count.
    assert updates[0] == {"done": 0, "total": 5, "phase": None}
    assert updates[-1]["done"] == len(result.reactors) == 2
    assert [u["phase"] for u in updates] == [None, "love", "haha"]
    assert all(u["total"] == 5 for u in updates)  # stable expected_total throughout


def test_fetch_with_page_full_set_filter_behaves_like_unfiltered():
    rows_by_index = {
        0: [{"name": "John", "profile_url": "https://www.facebook.com/john.doe.5", "avatar_url": AVATAR_J}],
        1: [{"name": "Sara", "profile_url": "https://www.facebook.com/sara.x", "avatar_url": AVATAR_A}],
    }
    page = _StubPage(rows_by_index)
    result = fetch_with_page(page, _config(reaction_types=tuple(REACTION_LABELS)))
    assert {r.profile_key for r in result.reactors} == {"john.doe.5", "sara.x"}
    # Nothing was narrowed, so the summary count still wins as the target.
    assert result.expected_total == 5
