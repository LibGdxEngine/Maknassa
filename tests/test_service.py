from __future__ import annotations

import pytest

from reactions.service import FacebookBlocker


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
