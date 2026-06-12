"""API-layer tests: the whole job lifecycle without a real browser.

The core browser seams (``fetch_reactors`` / ``login_flow`` / ``FacebookBlocker``)
are imported as attributes of :mod:`reactions.api`, so every test here monkeypatches
``reactions.api.<seam>`` with a stub -- no Chromium, no Facebook -- and drives the
async job manager via the HTTP surface (``fastapi.testclient.TestClient``). Jobs run
on background threads, so assertions poll with a short deadline instead of sleeping.

A per-test ``data_dir`` fixture repoints ``MAKNASSA_DATA_DIR`` at a fresh tmp dir
(``paths.app_data_dir`` reads that env var live), so settings/account persistence is
isolated and never touches the session-wide conftest dir.
"""

from __future__ import annotations

import threading
import time
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient

import reactions.api as api
from reactions.api import create_app
from reactions.models import BlockOutcome
from reactions.selectors import REACTION_LABELS
from reactions.ui_fetch import FetchResult, UIReactor

TOKEN = "test-token"
AUTH = {"X-Maknassa-Token": TOKEN}


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Isolate persisted state (ui_state.json) under a fresh per-test data dir."""
    monkeypatch.setenv("MAKNASSA_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def client(data_dir):
    with TestClient(create_app(TOKEN)) as test_client:
        yield test_client


def _poll_job(client: TestClient, job_id: str, *, until, timeout_s: float = 5.0) -> dict[str, Any]:
    """Poll GET /api/jobs/{id} until ``until(job)`` is true (or the deadline)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if until(job):
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never satisfied the condition: last={job}")


def _await_done(client: TestClient, job_id: str, **kw) -> dict[str, Any]:
    return _poll_job(client, job_id, until=lambda j: j["state"] != "running", **kw)


# --------------------------------------------------------------------------- #
# Auth + health
# --------------------------------------------------------------------------- #
def test_health_needs_no_auth(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert isinstance(body["version"], str) and body["version"]


def test_protected_routes_reject_missing_token(client):
    assert client.get("/api/session").status_code == 401
    assert client.get("/api/session").json() == {"error": "unauthorized"}


def test_protected_routes_reject_wrong_token(client):
    resp = client.get("/api/session", headers={"X-Maknassa-Token": "nope"})
    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized"}


# --------------------------------------------------------------------------- #
# Settings round-trip + persistence
# --------------------------------------------------------------------------- #
def test_settings_defaults_then_round_trip(client, data_dir):
    initial = client.get("/api/settings", headers=AUTH).json()
    assert initial["headless"] is False
    assert initial["min_delay"] == 2.0 and initial["max_delay"] == 6.0
    assert initial["stop_after"] == 0
    assert initial["profile_dir"]  # a default profile dir is always present

    saved = client.put(
        "/api/settings",
        headers=AUTH,
        json={"headless": True, "min_delay": 1.5, "stop_after": 7},
    ).json()
    assert saved["headless"] is True
    assert saved["min_delay"] == 1.5
    assert saved["stop_after"] == 7
    assert saved["max_delay"] == 6.0  # untouched fields keep their value

    # Persisted to disk: a brand-new app over the SAME data dir sees the change.
    with TestClient(create_app(TOKEN)) as fresh:
        reloaded = fresh.get("/api/settings", headers=AUTH).json()
    assert reloaded["headless"] is True
    assert reloaded["stop_after"] == 7
    assert (data_dir / "ui_state.json").exists()


def test_settings_tolerates_corrupt_state_file(client, data_dir):
    (data_dir / "ui_state.json").write_text("{not valid json", encoding="utf-8")
    body = client.get("/api/settings", headers=AUTH).json()
    assert body["headless"] is False  # falls back to defaults rather than 500ing


# --------------------------------------------------------------------------- #
# Fetch job lifecycle
# --------------------------------------------------------------------------- #
def test_fetch_job_serializes_result(client, monkeypatch):
    reactor = UIReactor(
        name="Alice",
        profile_url="https://www.facebook.com/alice",
        profile_key="alice",
        reaction_type="like",
        avatar_url=None,
    )
    captured: dict[str, Any] = {}

    def fake_fetch(config):
        captured["post_url"] = config.post_url
        captured["reaction_types"] = config.reaction_types
        return FetchResult(reactors=[reactor], expected_total=3)

    monkeypatch.setattr(api, "fetch_reactors", fake_fetch)

    resp = client.post("/api/fetch", headers=AUTH, json={"post_url": "https://fb/post"})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = _await_done(client, job_id)
    assert job["state"] == "done"
    assert job["kind"] == "fetch"
    assert job["result"]["expected_total"] == 3
    assert job["result"]["reactors"][0]["name"] == "Alice"
    assert job["result"]["reactors"][0]["reaction_type"] == "like"
    assert captured["post_url"] == "https://fb/post"
    assert captured["reaction_types"] is None  # field omitted = fetch all


def test_fetch_threads_reaction_types_into_config(client, monkeypatch):
    captured: dict[str, Any] = {}

    def fake_fetch(config):
        captured["reaction_types"] = config.reaction_types
        return FetchResult(reactors=[], expected_total=0)

    monkeypatch.setattr(api, "fetch_reactors", fake_fetch)

    body = {"post_url": "https://fb/post", "reaction_types": ["haha", "love", "haha"]}
    resp = client.post("/api/fetch", headers=AUTH, json=body)
    assert resp.status_code == 202
    _await_done(client, resp.json()["job_id"])
    assert captured["reaction_types"] == ("haha", "love")  # deduped, order kept


def test_fetch_empty_reaction_types_means_all(client, monkeypatch):
    captured: dict[str, Any] = {}

    def fake_fetch(config):
        captured["reaction_types"] = config.reaction_types
        return FetchResult(reactors=[], expected_total=0)

    monkeypatch.setattr(api, "fetch_reactors", fake_fetch)

    body = {"post_url": "https://fb/post", "reaction_types": []}
    resp = client.post("/api/fetch", headers=AUTH, json=body)
    assert resp.status_code == 202
    _await_done(client, resp.json()["job_id"])
    assert captured["reaction_types"] is None


def test_fetch_rejects_unknown_reaction_types(client):
    body = {"post_url": "https://fb/post", "reaction_types": ["haha", "banana"]}
    resp = client.post("/api/fetch", headers=AUTH, json=body)
    assert resp.status_code == 422  # off-Literal value -> validation error, no job


def test_reaction_type_literal_matches_canonical_keys():
    # Guards drift between the API's Literal and selectors.REACTION_LABELS.
    assert set(get_args(api.ReactionType)) == set(REACTION_LABELS)


def test_unknown_job_is_404(client):
    resp = client.get("/api/jobs/does-not-exist", headers=AUTH)
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Login job lifecycle
# --------------------------------------------------------------------------- #
def test_login_success_persists_account_and_connects(client, monkeypatch):
    monkeypatch.setattr(api, "login_flow", lambda config, timeout_s=300: "100012345")

    assert client.get("/api/session", headers=AUTH).json()["connected"] is False

    resp = client.post("/api/login", headers=AUTH, json={"timeout_s": 5})
    assert resp.status_code == 202
    job = _await_done(client, resp.json()["job_id"])
    assert job["state"] == "done"
    assert job["result"] == {"account_id": "100012345"}

    session = client.get("/api/session", headers=AUTH).json()
    assert session["connected"] is True
    assert session["account_id"] == "100012345"


def test_settings_put_preserves_account_id(client, monkeypatch):
    """A settings PUT must not clobber the account_id the login flow stored.

    Both write the same ui_state.json from different threads; this locks the
    read-modify-write contract that keeps the two fields independent.
    """
    monkeypatch.setattr(api, "login_flow", lambda config, timeout_s=300: "100012345")
    resp = client.post("/api/login", headers=AUTH, json={"timeout_s": 5})
    _await_done(client, resp.json()["job_id"])
    assert client.get("/api/session", headers=AUTH).json()["connected"] is True

    saved = client.put("/api/settings", headers=AUTH, json={"headless": True, "stop_after": 9})
    assert saved.status_code == 200
    assert saved.json()["headless"] is True

    session = client.get("/api/session", headers=AUTH).json()
    assert session["connected"] is True
    assert session["account_id"] == "100012345"


def test_settings_clamps_negative_values(client):
    """Negative stop_after/delays clamp to 0 (no cap / no negative pause)."""
    saved = client.put(
        "/api/settings", headers=AUTH, json={"stop_after": -5, "min_delay": -1.0}
    ).json()
    assert saved["stop_after"] == 0
    assert saved["min_delay"] == 0.0


def test_login_timeout_is_error_state(client, monkeypatch):
    monkeypatch.setattr(api, "login_flow", lambda config, timeout_s=300: None)

    resp = client.post("/api/login", headers=AUTH, json={"timeout_s": 1})
    job = _await_done(client, resp.json()["job_id"])
    assert job["state"] == "error"
    assert job["error"] == "login-timeout"
    # A failed login must NOT mark the session connected.
    assert client.get("/api/session", headers=AUTH).json()["connected"] is False


# --------------------------------------------------------------------------- #
# Block job: progress accumulation, stop_after, cancel
# --------------------------------------------------------------------------- #
class _RecordingBlocker:
    """Stub FacebookBlocker: records each blocked url, no browser involved."""

    calls: list[str] = []

    def __init__(self, *args, **kwargs):
        type(self).calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def block(self, url, name=None):
        type(self).calls.append(url)
        return BlockOutcome(profile_key=url, name=None, profile_url=url, status="blocked")

    def unblock(self, url, name=None):
        type(self).calls.append(url)
        return BlockOutcome(profile_key=url, name=None, profile_url=url, status="unblocked")


def test_block_job_accumulates_progress(client, monkeypatch):
    monkeypatch.setattr(api, "FacebookBlocker", _RecordingBlocker)
    # Zero pacing keeps the test fast (the human pause between successes is 0s).
    client.put("/api/settings", headers=AUTH, json={"min_delay": 0.0, "max_delay": 0.0})
    urls = [f"https://fb/{i}" for i in range(3)]

    resp = client.post("/api/block", headers=AUTH, json={"profile_urls": urls})
    assert resp.status_code == 202
    job = _await_done(client, resp.json()["job_id"])

    assert job["state"] == "done"
    assert job["progress"]["total"] == 3
    assert job["progress"]["done"] == 3
    assert [o["status"] for o in job["progress"]["outcomes"]] == ["blocked"] * 3
    assert [o["status"] for o in job["result"]] == ["blocked"] * 3
    assert _RecordingBlocker.calls == urls


def test_block_job_honors_stop_after(client, monkeypatch):
    monkeypatch.setattr(api, "FacebookBlocker", _RecordingBlocker)
    # stop_after == 2: only the first two successes are acted on. Zero pacing keeps it fast.
    client.put(
        "/api/settings", headers=AUTH, json={"stop_after": 2, "min_delay": 0.0, "max_delay": 0.0}
    )
    urls = [f"https://fb/{i}" for i in range(5)]

    resp = client.post("/api/block", headers=AUTH, json={"profile_urls": urls})
    job = _await_done(client, resp.json()["job_id"])

    assert job["state"] == "done"
    assert len(job["result"]) == 2
    assert _RecordingBlocker.calls == urls[:2]


def test_block_job_cancel_between_items(client, monkeypatch):
    """Cancel flips state to 'cancelled' and stops further items mid-batch."""
    gate = threading.Event()
    started = threading.Event()

    class _GatedBlocker(_RecordingBlocker):
        def block(self, url, name=None):
            started.set()
            gate.wait(timeout=5)  # hold on the first item until the test cancels
            return super().block(url, name)

    monkeypatch.setattr(api, "FacebookBlocker", _GatedBlocker)
    client.put("/api/settings", headers=AUTH, json={"min_delay": 0.0, "max_delay": 0.0})
    urls = [f"https://fb/{i}" for i in range(5)]

    resp = client.post("/api/block", headers=AUTH, json={"profile_urls": urls})
    job_id = resp.json()["job_id"]
    assert started.wait(timeout=5)

    assert client.post(f"/api/jobs/{job_id}/cancel", headers=AUTH).json() == {"cancelled": True}
    gate.set()  # let the in-flight first item finish; the loop then sees the cancel

    job = _await_done(client, job_id)
    assert job["state"] == "cancelled"
    assert len(_GatedBlocker.calls) < len(urls)  # did not process the whole batch


# --------------------------------------------------------------------------- #
# Single-running-browser-job rule (409 busy)
# --------------------------------------------------------------------------- #
def test_second_browser_job_is_busy_409(client, monkeypatch):
    release = threading.Event()

    def slow_fetch(config):
        release.wait(timeout=5)
        return FetchResult(reactors=[], expected_total=0)

    monkeypatch.setattr(api, "fetch_reactors", slow_fetch)

    first = client.post("/api/fetch", headers=AUTH, json={"post_url": "https://fb/post"})
    assert first.status_code == 202
    running_id = first.json()["job_id"]

    # Wait until the first job is actually occupying the running slot.
    _poll_job(client, running_id, until=lambda j: j["state"] == "running")

    second = client.post("/api/block", headers=AUTH, json={"profile_urls": ["https://fb/x"]})
    assert second.status_code == 409
    body = second.json()
    assert body["error"] == "busy"
    assert body["job_id"] == running_id

    release.set()  # let the first job finish so the client teardown is clean
    _await_done(client, running_id)
