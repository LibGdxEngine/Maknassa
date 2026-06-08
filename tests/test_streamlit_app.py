"""Render-path tests for streamlit_app.py via Streamlit's AppTest harness.

These execute the app script in a simulated Streamlit context (no browser, no
network): they verify it renders without error, the URL guard warns, and the
fetched-reactor display wires checkboxes, select-all, and the confirmation-gated
block button correctly. The actual fetch/block (which drive Playwright) are never
clicked, so no real browser launches.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from reactions.ui_fetch import UIReactor  # noqa: E402


def _app() -> AppTest:
    return AppTest.from_file("streamlit_app.py", default_timeout=30)


def _reactor(key: str, name: str, rtype: str, avatar: str | None = None) -> UIReactor:
    return UIReactor(
        name=name,
        profile_url=f"https://www.facebook.com/{key}",
        profile_key=key,
        reaction_type=rtype,
        avatar_url=avatar,
    )


def _sel_checkboxes(at: AppTest):
    return [c for c in at.checkbox if (c.key or "").startswith("sel_")]


def test_app_renders_without_error():
    at = _app().run()
    assert not at.exception
    assert any("Reactor Blocker" in (m.value or "") for m in at.title)


def test_empty_url_fetch_warns_and_does_not_crash():
    at = _app().run()
    fetch = next(b for b in at.button if b.label == "Fetch reactors")
    fetch.click().run()
    assert not at.exception
    assert any("Paste a post URL" in w.value for w in at.warning)


def test_reactors_render_with_checkboxes_and_gated_block():
    at = _app()
    at.session_state["reactors"] = [
        _reactor("john.doe.5", "John", "love"),
        _reactor("100012345", "Ahmed", "angry"),
    ]
    at.run()
    assert not at.exception
    # One selection checkbox per reactor.
    assert len(_sel_checkboxes(at)) == 2
    labels = [b.label for b in at.button]
    assert "Select all" in labels and "Deselect all" in labels
    # Nothing selected and unconfirmed -> block button disabled, count 0.
    block = next(b for b in at.button if b.label.startswith("Block selected"))
    assert block.label == "Block selected (0)"
    assert block.disabled


def test_select_all_then_confirm_enables_block():
    at = _app()
    at.session_state["reactors"] = [_reactor("john.doe.5", "John", "love")]
    at.run()
    next(b for b in at.button if b.label == "Select all").click().run()
    block = next(b for b in at.button if b.label.startswith("Block selected"))
    assert block.label == "Block selected (1)"
    assert block.disabled  # selected, but not yet confirmed
    next(c for c in at.checkbox if c.key == "confirm_block").check().run()
    block = next(b for b in at.button if b.label.startswith("Block selected"))
    assert not block.disabled  # selected AND confirmed


def test_refetch_clears_stale_selection_and_consent(monkeypatch):
    """A new fetch must reset selection + the confirmation box so each block batch
    requires deliberate fresh consent (the block is irreversible)."""
    import reactions.ui_fetch as uf

    fresh = [_reactor("zee", "Zee", "like")]
    # Stub the threaded browser call so fetch returns a canned FetchResult, no browser.
    monkeypatch.setattr(
        uf, "in_thread", lambda fn, *a, **k: uf.FetchResult(reactors=list(fresh), expected_total=1)
    )

    at = _app()
    # Simulate a prior post: a selected reactor with consent already given.
    at.session_state["reactors"] = [_reactor("old", "Old", "love")]
    at.session_state["sel_old"] = True
    at.session_state["confirm_block"] = True
    at.run()

    url = next(t for t in at.text_input if t.label == "Facebook post URL")
    url.set_value("https://www.facebook.com/page/posts/9").run()
    next(b for b in at.button if b.label == "Fetch reactors").click().run()

    assert not at.exception
    # New reactor set is in place...
    assert [r.profile_key for r in at.session_state["reactors"]] == ["zee"]
    # ...with the stale selection gone and consent reset to unchecked.
    assert "sel_old" not in at.session_state
    assert not next(c for c in at.checkbox if c.key == "confirm_block").value
    assert next(b for b in at.button if b.label.startswith("Block selected")).label == "Block selected (0)"


def test_summary_shows_completeness_meter_and_warns_on_large_gap():
    """When Facebook's own count exceeds what was captured, the summary shows the
    shortfall and warns on a large gap (the virtualization-miss signature)."""
    at = _app()
    at.session_state["reactors"] = [_reactor("a", "A", "like")]
    at.session_state["expected_total"] = 508
    at.run()
    assert not at.exception
    assert any("of 508 reactor(s) captured" in (m.value or "") for m in at.markdown)
    assert any("not captured" in (w.value or "") for w in at.warning)


def test_summary_hides_meter_when_counts_match():
    """No 'of N' meter and no warning when captured >= expected (or expected is 0)."""
    at = _app()
    at.session_state["reactors"] = [_reactor("a", "A", "like")]
    at.session_state["expected_total"] = 1
    at.run()
    assert not at.exception
    assert not any("captured" in (m.value or "") for m in at.markdown)
    assert not any("not captured" in (w.value or "") for w in at.warning)


def test_deselect_all_clears_selection():
    at = _app()
    at.session_state["reactors"] = [
        _reactor("john.doe.5", "John", "love"),
        _reactor("100012345", "Ahmed", "angry"),
    ]
    at.run()
    next(b for b in at.button if b.label == "Select all").click().run()
    assert next(b for b in at.button if b.label.startswith("Block selected")).label == "Block selected (2)"
    next(b for b in at.button if b.label == "Deselect all").click().run()
    assert next(b for b in at.button if b.label.startswith("Block selected")).label == "Block selected (0)"
