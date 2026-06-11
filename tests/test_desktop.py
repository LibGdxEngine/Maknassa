"""Unit tests for the desktop launcher's pure helpers (no GUI, no server boot)."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

from reactions import desktop


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_streamlit_argv_is_headless_localhost_with_port():
    argv = desktop.streamlit_argv(Path("/app/streamlit_app.py"), 8765)
    assert argv[:3] == ["streamlit", "run", "/app/streamlit_app.py"]
    assert argv[argv.index("--server.port") + 1] == "8765"
    assert argv[argv.index("--server.address") + 1] == "127.0.0.1"
    assert argv[argv.index("--server.headless") + 1] == "true"
    assert argv[argv.index("--browser.gatherUsageStats") + 1] == "false"


def test_free_port_respects_pin(monkeypatch):
    monkeypatch.setenv("MAKNASSA_GUI_PORT", "12345")
    assert desktop.free_port() == 12345


def test_free_port_picks_open_port(monkeypatch):
    monkeypatch.delenv("MAKNASSA_GUI_PORT", raising=False)
    port = desktop.free_port()
    assert 1024 < port < 65536


def test_resolve_script_path_points_at_app():
    script = desktop.resolve_script_path()
    assert script.name == "streamlit_app.py"
    assert script.exists()  # in a source checkout the repo file is present


def test_wait_for_server_true_when_listening():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert desktop.wait_for_server(port, timeout_s=2.0) is True
    finally:
        srv.close()


def test_find_bundled_chromium_picks_headed_chrome_not_headless_shell(monkeypatch, tmp_path):
    chrome = _touch(tmp_path / "chromium-1208" / "chrome-linux64" / "chrome")
    _touch(
        tmp_path
        / "chromium_headless_shell-1208"
        / "chrome-headless-shell-linux64"
        / "chrome-headless-shell"
    )
    monkeypatch.setattr(desktop, "resolve_browsers_path", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")
    assert desktop.find_bundled_chromium() == chrome


def test_find_bundled_chromium_none_without_bundled_browsers(monkeypatch):
    monkeypatch.setattr(desktop, "resolve_browsers_path", lambda: None)
    assert desktop.find_bundled_chromium() is None


def test_pywebview_backend_needs_gi_or_qtpy_on_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(desktop.importlib.util, "find_spec", lambda name: None)
    assert desktop._pywebview_has_backend() is False


def test_pywebview_backend_assumed_present_off_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert desktop._pywebview_has_backend() is True


def test_wait_for_server_false_when_down():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()  # free the port so nothing is listening
    assert desktop.wait_for_server(port, timeout_s=0.5) is False
