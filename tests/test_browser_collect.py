"""Unit tests for the store-free collection seam (ReactionScraper._collect_active_tab).

These exercise the row -> normalized-record path with a stubbed Playwright page
(no live browser, no database), which is exactly what extracting the seam from
the persistence/store logic made possible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reactions.browser import (
    ReactionScraper,
    _launch_kwargs,
    collect_records,
    select_targets,
)
from reactions.config import ReactionConfig
from reactions.selectors import REACTION_LABELS

POST_URL = "https://www.facebook.com/some.page/posts/123456789"


class _StubLocator:
    def __init__(self, lang: str | None) -> None:
        self._lang = lang

    def get_attribute(self, _name: str) -> str | None:
        return self._lang


class _StubPage:
    """Minimal stand-in for a Playwright Page: returns canned rows + locale."""

    def __init__(self, rows, lang: str | None = "en") -> None:
        self._rows = rows
        self._lang = lang

    def locator(self, _selector: str) -> _StubLocator:
        return _StubLocator(self._lang)

    def evaluate(self, _script, _arg=None):
        return self._rows


def _scraper() -> ReactionScraper:
    config = ReactionConfig(
        post_url=POST_URL,
        db_path=Path("unused.db"),
        profile_dir=Path("/tmp/unused"),
    )
    # store is unused by _collect_active_tab — the whole point of the seam.
    return ReactionScraper(config, store=None)  # type: ignore[arg-type]


def test_collect_dedups_by_profile_id_and_rejects_non_profiles():
    rows = [
        {"name": "Ahmed", "profile_url": "https://www.facebook.com/profile.php?id=100012345&__tn__=R"},
        # Same numeric id (tracking stripped) -> de-duplicated away.
        {"name": "Ahmed again", "profile_url": "https://www.facebook.com/profile.php?id=100012345"},
        {"name": "John", "profile_url": "https://www.facebook.com/john.doe.5"},
        # Non-profile links are rejected by parse_reactor.
        {"name": "A Group", "profile_url": "https://www.facebook.com/groups/999"},
        {"name": "A Post", "profile_url": "https://www.facebook.com/some.page/posts/1"},
        {"name": "No URL", "profile_url": None},
    ]
    scraper = _scraper()
    records = scraper._collect_active_tab(_StubPage(rows), "angry")

    assert {r.profile_key for r in records} == {"100012345", "john.doe.5"}
    assert all(r.reaction_type == "angry" for r in records)
    # Every raw row is counted as discovered, even the ones later dropped.
    assert scraper.stats.discovered_rows == len(rows)


def test_collect_records_pure_pipeline_dedups_and_rejects():
    """The extracted pure pipeline runs with no scraper, page, or DB at all."""
    rows = [
        {"name": "Ahmed", "profile_url": "https://www.facebook.com/profile.php?id=100012345&__tn__=R"},
        {"name": "Ahmed again", "profile_url": "https://www.facebook.com/profile.php?id=100012345"},
        {"name": "John", "profile_url": "https://www.facebook.com/john.doe.5"},
        {"name": "A Group", "profile_url": "https://www.facebook.com/groups/999"},
        {"name": "No URL", "profile_url": None},
    ]
    records = collect_records(POST_URL, "love", "ar", rows)
    assert [r.profile_key for r in records] == ["100012345", "john.doe.5"]
    assert all(r.reaction_type == "love" for r in records)


def test_collect_records_tags_reaction_type():
    """The pure function stamps each record with the tab's reaction type."""
    rows = [{"name": "John", "profile_url": "https://www.facebook.com/john.doe.5"}]
    records = collect_records(POST_URL, "like", "en", rows)
    assert records[0].reaction_type == "like"


def test_collect_propagates_evaluate_errors():
    """The seam does not swallow errors; the caller (_scrape_active_tab) records them."""

    class _Boom(_StubPage):
        def evaluate(self, _script, _arg=None):
            raise RuntimeError("page crashed")

    scraper = _scraper()
    with pytest.raises(RuntimeError, match="page crashed"):
        scraper._collect_active_tab(_Boom([]), "like")


def test_select_targets_prefers_per_type_tabs():
    tabs = [
        {"index": 0, "aria": "All", "text": "All 50", "alts": []},
        {"index": 1, "aria": "Angry", "text": "Angry 12", "alts": []},
        {"index": 2, "aria": "Haha", "text": "Haha 8", "alts": []},
    ]
    targets = select_targets(tabs)
    assert {(t[1], t[2]) for t in targets} == {("angry", 12), ("haha", 8)}  # 'all' dropped


def test_select_targets_falls_back_to_all_then_unknown():
    only_all = [{"index": 0, "aria": "All reactions", "text": "All 50", "alts": []}]
    assert select_targets(only_all) == [(0, "all", 50)]
    assert select_targets([]) == [(-1, "unknown", 0)]  # nothing recognizable


def test_select_targets_filters_to_allowed_types():
    tabs = [
        {"index": 0, "aria": "All", "text": "All 50", "alts": []},
        {"index": 1, "aria": "Angry", "text": "Angry 12", "alts": []},
        {"index": 2, "aria": "Haha", "text": "Haha 8", "alts": []},
    ]
    assert select_targets(tabs, {"haha"}) == [(2, "haha", 8)]
    # The full canonical set narrows nothing.
    assert select_targets(tabs, set(REACTION_LABELS)) == select_targets(tabs)


def test_select_targets_filter_no_match_returns_empty():
    tabs = [{"index": 1, "aria": "Angry", "text": "Angry 12", "alts": []}]
    # A legitimate zero ("no reactors of the selected types") -- the 'all'/unknown
    # fallback must NOT kick in and scrape everything.
    assert select_targets(tabs, {"love"}) == []


def test_select_targets_filter_ignored_without_per_type_tabs():
    # No per-type tabs -> no types to filter on; scrape the fallback as-is.
    only_all = [{"index": 0, "aria": "All reactions", "text": "All 50", "alts": []}]
    assert select_targets(only_all, {"haha"}) == [(0, "all", 50)]
    assert select_targets([], {"haha"}) == [(-1, "unknown", 0)]


def test_select_targets_none_and_empty_allowed_mean_all():
    tabs = [
        {"index": 1, "aria": "Angry", "text": "Angry 12", "alts": []},
        {"index": 2, "aria": "Haha", "text": "Haha 8", "alts": []},
    ]
    assert select_targets(tabs, None) == select_targets(tabs)
    assert select_targets(tabs, ()) == select_targets(tabs)


def test_scrape_all_tabs_honors_config_reaction_types(monkeypatch):
    """The CLI twin threads config.reaction_types into select_targets."""
    scraper = _scraper()
    scraper.config.reaction_types = ("haha",)
    monkeypatch.setattr(
        "reactions.browser.select_reaction_tab", lambda page, config, index, rtype: True
    )
    scraped: list[str] = []
    monkeypatch.setattr(
        scraper,
        "_scrape_active_tab",
        lambda page, session_id, reaction_type, target: scraped.append(reaction_type) or 0,
    )
    tabs = [
        {"index": 1, "aria": "Angry", "text": "Angry 12", "alts": []},
        {"index": 2, "aria": "Haha", "text": "Haha 8", "alts": []},
    ]
    scraper._scrape_all_tabs(_StubPage(tabs), session_id=1)
    assert scraped == ["haha"]  # the Angry tab is never scraped
    assert scraper.stats.per_type_expected == {"haha": 8}


def test_warn_on_undercount_flags_large_gaps(caplog):
    scraper = _scraper()
    scraper.stats.per_type_expected = {"angry": 100, "like": 10}
    scraper.stats.per_type_counts = {"angry": 40, "like": 9}  # angry: big gap, like: within tolerance
    with caplog.at_level("WARNING"):
        scraper._warn_on_undercount()
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "angry" in messages
    assert "like" not in messages


# --------------------------------------------------------------------------- #
# Browser launch kwargs: headed sessions track the real window (no fixed viewport
# that clips login/confirm controls off-screen); headless keeps a fixed viewport.
# --------------------------------------------------------------------------- #
def test_launch_kwargs_headed_uses_real_window():
    kwargs = _launch_kwargs("/tmp/profile", is_headless=False)
    assert kwargs["no_viewport"] is True
    assert kwargs["args"] == ["--start-maximized"]
    assert "viewport" not in kwargs  # a fixed viewport would clip the window
    assert kwargs["headless"] is False
    assert kwargs["channel"] == "chromium"
    assert kwargs["user_data_dir"] == "/tmp/profile"


def test_launch_kwargs_headless_uses_fixed_viewport():
    kwargs = _launch_kwargs("/tmp/profile", is_headless=True)
    assert kwargs["viewport"] == {"width": 1440, "height": 1600}
    assert "no_viewport" not in kwargs
    assert "args" not in kwargs
    assert kwargs["headless"] is True
    assert kwargs["channel"] == "chromium"
