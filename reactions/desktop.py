"""Desktop shell: run the Streamlit UI locally inside a native window.

``maknassa-gui`` starts the project's Streamlit app on a random localhost port (in
a child process so Streamlit's signal handlers get a real main thread, and so a
PyInstaller-frozen build can re-exec itself cleanly), waits for it to come up,
then opens it in a ``pywebview`` window. Closing the window stops the server.

Nothing here talks to Facebook -- that all still happens in the existing
``reactions`` core, which the Streamlit app drives on its own worker thread.

Env knobs:
* ``MAKNASSA_NO_WINDOW=1`` -- run the server only and print the URL (headless /
  server hosting / CI). Used by the smoke test where no display is available.
* ``MAKNASSA_GUI_PORT``     -- pin the port instead of picking a free one.
"""

from __future__ import annotations

import multiprocessing
import os
import socket
import sys
import time
from pathlib import Path

WINDOW_TITLE = "Maknassa — Reactor Blocker"
_HOST = "127.0.0.1"


def is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def bundle_dir() -> Path:
    """Root of bundled data files (``sys._MEIPASS`` when frozen, else repo root)."""
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]  # set by PyInstaller at runtime
    return Path(__file__).resolve().parent.parent


def resolve_script_path() -> Path:
    """Locate ``streamlit_app.py`` for both source runs and frozen bundles."""
    return bundle_dir() / "streamlit_app.py"


def resolve_browsers_path() -> Path | None:
    """Bundled Playwright browser dir, if present (frozen builds ship it here)."""
    candidate = bundle_dir() / "ms-playwright"
    return candidate if candidate.exists() else None


def free_port() -> int:
    pinned = os.environ.get("MAKNASSA_GUI_PORT")
    if pinned:
        return int(pinned)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((_HOST, 0))
        return int(sock.getsockname()[1])


def streamlit_argv(script_path: Path, port: int) -> list[str]:
    """The ``streamlit run`` argv used to serve the app headless on localhost."""
    return [
        "streamlit",
        "run",
        str(script_path),
        "--server.port",
        str(port),
        "--server.address",
        _HOST,
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
        "--global.developmentMode",
        "false",
    ]


def _apply_runtime_env() -> None:
    """Env that must be set before the app imports Streamlit/Playwright."""
    os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    os.environ.setdefault("BROWSER", "none")
    browsers = resolve_browsers_path()
    if browsers is not None:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)


def _serve(script_path: str, port: int) -> None:
    """Child-process entry point: run Streamlit's CLI in this process's main thread."""
    _apply_runtime_env()
    sys.argv = streamlit_argv(Path(script_path), port)
    from streamlit.web import cli as stcli

    stcli.main()


def wait_for_server(port: int, timeout_s: float = 60.0) -> bool:
    """Poll the localhost port until it accepts connections (or we time out)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            if sock.connect_ex((_HOST, port)) == 0:
                return True
        time.sleep(0.25)
    return False


def main() -> int:
    multiprocessing.freeze_support()
    # 'spawn' keeps the child clean and matches the only frozen-safe method on
    # Windows/macOS; on Linux it avoids inheriting the parent's import state.
    ctx = multiprocessing.get_context("spawn")
    _apply_runtime_env()

    script = resolve_script_path()
    if not script.exists():
        print(f"error: could not find the UI script at {script}", file=sys.stderr)
        return 1

    port = free_port()
    server = ctx.Process(target=_serve, args=(str(script), port), daemon=True)
    server.start()

    url = f"http://{_HOST}:{port}"
    if not wait_for_server(port):
        print("error: Streamlit server did not start in time", file=sys.stderr)
        server.terminate()
        return 1

    if os.environ.get("MAKNASSA_NO_WINDOW") == "1":
        print(f"Maknassa UI running (no-window mode): {url}\nPress Ctrl-C to stop.")
        try:
            server.join()
        except KeyboardInterrupt:
            pass
        finally:
            server.terminate()
        return 0

    import webview  # imported lazily so headless/no-window runs need no GUI backend

    webview.create_window(WINDOW_TITLE, url, width=1280, height=900)
    try:
        webview.start()
    finally:
        server.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
