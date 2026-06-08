"""Licence-gate tests: activation, offline grace, revocation, dev bypass.

All network I/O is monkeypatched (``licensing._post``); the licence token is
written into a temp ``MAKNASSA_DATA_DIR`` so nothing touches the real config dir.
"""

from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest

from reactions import licensing, paths


@pytest.fixture
def unlicensed_env(tmp_path, monkeypatch):
    """No dev bypass, isolated data dir -> the app starts out unactivated."""
    monkeypatch.delenv("MAKNASSA_DEV", raising=False)
    monkeypatch.setenv("MAKNASSA_DATA_DIR", str(tmp_path))
    return tmp_path


def _ok_activation(_endpoint, payload):
    return {
        "activated": True,
        "instance": {"id": "inst-1", "name": payload["instance_name"]},
        "license_key": {"status": "active"},
    }


def _age_token_to(days_ago: float) -> None:
    token = json.loads(paths.license_path().read_text())
    token["last_validated_at"] = (
        datetime.now(timezone.utc) - timedelta(days=days_ago)
    ).isoformat()
    paths.license_path().write_text(json.dumps(token))


def test_unactivated_by_default(unlicensed_env):
    assert licensing.is_activated() is False
    assert "Not activated" in licensing.status().detail


def test_activate_persists_token_and_unlocks(unlicensed_env, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        licensing, "_post", lambda e, p: seen.update(endpoint=e, payload=p) or _ok_activation(e, p)
    )
    result = licensing.activate("KEY-1234-5678-ABCD")
    assert result.activated
    assert seen["endpoint"] == "activate"
    assert seen["payload"]["instance_name"].startswith("Maknassa-")
    assert paths.license_path().exists()
    assert licensing.is_activated() is True  # within the recheck window


def test_activate_rejects_invalid_key(unlicensed_env, monkeypatch):
    monkeypatch.setattr(licensing, "_post", lambda e, p: {"activated": False, "error": "not found"})
    result = licensing.activate("bad-key")
    assert not result.activated
    assert not paths.license_path().exists()
    assert licensing.is_activated() is False


def test_activate_offline_is_graceful(unlicensed_env, monkeypatch):
    def boom(_e, _p):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(licensing, "_post", boom)
    result = licensing.activate("KEY")
    assert not result.activated
    assert "Could not reach" in result.detail


def test_offline_within_grace_stays_activated(unlicensed_env, monkeypatch):
    monkeypatch.setattr(licensing, "_post", _ok_activation)
    licensing.activate("KEY")
    _age_token_to(days_ago=3)  # past recheck (1d), within grace (7d)

    def boom(_e, _p):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(licensing, "_post", boom)
    assert licensing.is_activated() is True


def test_offline_past_grace_locks_out(unlicensed_env, monkeypatch):
    monkeypatch.setattr(licensing, "_post", _ok_activation)
    licensing.activate("KEY")
    _age_token_to(days_ago=30)  # past the grace window

    def boom(_e, _p):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(licensing, "_post", boom)
    assert licensing.is_activated() is False


def test_revoked_validation_clears_token(unlicensed_env, monkeypatch):
    monkeypatch.setattr(licensing, "_post", _ok_activation)
    licensing.activate("KEY")
    _age_token_to(days_ago=3)  # force an online re-check
    monkeypatch.setattr(licensing, "_post", lambda e, p: {"valid": False, "error": "revoked"})
    assert licensing.is_activated() is False
    assert not paths.license_path().exists()


def test_deactivate_releases_and_clears(unlicensed_env, monkeypatch):
    monkeypatch.setattr(licensing, "_post", _ok_activation)
    licensing.activate("KEY")
    assert paths.license_path().exists()
    monkeypatch.setattr(licensing, "_post", lambda e, p: {"deactivated": True})
    assert licensing.deactivate() is True
    assert not paths.license_path().exists()


def test_dev_bypass_always_activated(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKNASSA_DEV", "1")
    monkeypatch.setenv("MAKNASSA_DATA_DIR", str(tmp_path))
    assert licensing.is_activated() is True
    assert licensing.status().activated is True


def test_machine_id_is_stable_and_opaque():
    first, second = licensing.machine_id(), licensing.machine_id()
    assert first == second
    assert len(first) == 32 and first.isalnum()
