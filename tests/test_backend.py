"""End-to-end backend smoke test: spawn the real process, talk to it, kill it.

Unlike :mod:`tests.test_api` (which drives the app in-process), this boots the
actual ``python -m reactions.backend`` subprocess the Electron main will spawn and
exercises the *contract surface*: the two stdout handshake lines, the
unauthenticated health probe, and one token-gated endpoint over real HTTP. The
token and data dir are pinned via env (``MAKNASSA_BACKEND_TOKEN`` /
``MAKNASSA_DATA_DIR``) so the test never needs to scrape the random token and never
touches the developer's real app-data dir. Kept well under 30s.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

TOKEN = "backend-test-token"
_HANDSHAKE_TIMEOUT_S = 20.0


def _read_handshake(proc: subprocess.Popen[str]) -> dict[str, str]:
    """Read the two ``KEY=value`` handshake lines from the child's stdout.

    Blocks per-line with an overall deadline so a backend that never announces
    itself fails the test loudly instead of hanging the suite.
    """
    values: dict[str, str] = {}
    deadline = time.monotonic() + _HANDSHAKE_TIMEOUT_S
    while len(values) < 2 and time.monotonic() < deadline:
        line = proc.stdout.readline() if proc.stdout else ""
        if not line:
            if proc.poll() is not None:  # the child died before announcing
                break
            continue
        line = line.strip()
        if line.startswith("MAKNASSA_BACKEND_") and "=" in line:
            key, _, value = line.partition("=")
            values[key] = value
    return values


def _get_json(url: str, token: str | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(url)
    if token is not None:
        request.add_header("X-Maknassa-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_backend_serves_handshake_and_endpoints(tmp_path):
    env = dict(os.environ)
    env["MAKNASSA_BACKEND_TOKEN"] = TOKEN
    env["MAKNASSA_DATA_DIR"] = str(tmp_path)

    proc = subprocess.Popen(
        [sys.executable, "-m", "reactions.backend"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )
    try:
        handshake = _read_handshake(proc)
        assert "MAKNASSA_BACKEND_PORT" in handshake, f"no port line; got {handshake}"
        assert handshake.get("MAKNASSA_BACKEND_TOKEN") == TOKEN
        port = int(handshake["MAKNASSA_BACKEND_PORT"])
        base = f"http://127.0.0.1:{port}"

        # The server may take a beat to start accepting connections after the
        # handshake prints; poll health until it answers (or a short deadline).
        deadline = time.monotonic() + 10.0
        status, body = 0, {}
        while time.monotonic() < deadline:
            try:
                status, body = _get_json(f"{base}/api/health")
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.1)
        assert status == 200, f"health never came up: {status} {body}"
        assert body["status"] == "ok"

        # Token-gated endpoint: 401 without the header, 200 with it.
        unauth_status, _ = _get_json(f"{base}/api/session")
        assert unauth_status == 401

        auth_status, session = _get_json(f"{base}/api/session", token=TOKEN)
        assert auth_status == 200
        assert session["connected"] is False
        assert session["data_dir"] == str(tmp_path)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    assert proc.returncode is not None  # the process actually exited


def test_apply_frozen_env_points_at_bundled_browsers(monkeypatch, tmp_path):
    from reactions import backend

    (tmp_path / "ms-playwright").mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    # Touch the var through monkeypatch first so its original state is restored.
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "sentinel")
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH")
    backend._apply_frozen_env()
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "ms-playwright")
