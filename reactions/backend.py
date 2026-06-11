"""Backend entrypoint: serve the reactions API on loopback and announce it.

``python -m reactions.backend`` boots the FastAPI app (:func:`reactions.api.create_app`)
under uvicorn on ``127.0.0.1`` and a free port, then runs until killed. It is the
process the Electron main spawns; the two find each other through a tiny stdout
**handshake** the Electron side parses:

    MAKNASSA_BACKEND_PORT=<port>
    MAKNASSA_BACKEND_TOKEN=<token>

Both lines are printed and flushed *before* uvicorn starts serving, so the parent
can read them, then poll the port. The token is a per-launch secret
(:func:`secrets.token_hex`) that gates every ``/api/*`` route except health; the
port is OS-assigned (bind to port 0, read it back) unless pinned. Both can be
overridden by env var so a test can fix them up front:

* ``MAKNASSA_BACKEND_PORT`` -- pin the listen port (else a free one is chosen).
* ``MAKNASSA_BACKEND_TOKEN`` -- pin the auth token (else a fresh random one).

**Parent watchdog.** A GUI backend must not outlive the window that spawned it
(an orphaned headless server would leak). When ``--parent-pid`` is given, a daemon
thread polls that pid every 2s with a signal-0 liveness probe and calls
``os._exit(0)`` the moment the parent is gone -- a hard exit, because uvicorn's own
shutdown can hang on in-flight browser work and we want a guaranteed teardown.
"""

from __future__ import annotations

import argparse
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from reactions.api import create_app

_HOST = "127.0.0.1"
_PORT_ENV = "MAKNASSA_BACKEND_PORT"
_TOKEN_ENV = "MAKNASSA_BACKEND_TOKEN"
_WATCHDOG_INTERVAL_S = 2.0


def free_port(host: str = _HOST) -> int:
    """An OS-assigned free TCP port (bind to 0, read it back), or the env pin.

    Mirrors ``desktop.free_port``: pinning via ``MAKNASSA_BACKEND_PORT`` lets a test
    fix the port before spawning; otherwise the kernel hands us an unused one, which
    we close and immediately reuse for uvicorn (a tiny race the loopback-only,
    single-launch context makes harmless).
    """
    pinned = os.environ.get(_PORT_ENV)
    if pinned:
        return int(pinned)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def make_token() -> str:
    """Per-launch auth secret, or the env override (so tests can pin it)."""
    return os.environ.get(_TOKEN_ENV) or secrets.token_hex(16)


def _pid_alive(pid: int) -> bool:
    """Whether ``pid`` is still running, via a psutil-free signal-0 probe.

    ``os.kill(pid, 0)`` sends no signal but performs the same permission/existence
    check the kernel would for a real signal: it raises ``ProcessLookupError`` once
    the process is gone, ``PermissionError`` while it merely belongs to another user
    (still alive), and returns cleanly when we own it and it lives.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def watch_parent(parent_pid: int, interval_s: float = _WATCHDOG_INTERVAL_S) -> None:
    """Block until ``parent_pid`` dies, then hard-exit this process.

    Run as a daemon thread. ``os._exit`` (not ``sys.exit``) skips interpreter
    cleanup and any uvicorn shutdown that could hang on an in-flight browser job --
    when the window is gone we want this server gone, immediately and unconditionally.
    """
    while _pid_alive(parent_pid):
        time.sleep(interval_s)
    os._exit(0)


def print_handshake(port: int, token: str) -> None:
    """Emit the two handshake lines and flush, so the parent can read them at once.

    Order and exact ``KEY=value`` shape are part of the frozen contract the Electron
    side parses; the explicit flush matters because the parent blocks on these lines
    before the (buffered) stdout would otherwise reach it.
    """
    sys.stdout.write(f"{_PORT_ENV}={port}\n")
    sys.stdout.write(f"{_TOKEN_ENV}={token}\n")
    sys.stdout.flush()


def _apply_frozen_env() -> None:
    """Point Playwright at the bundled Chromium when running as a frozen bundle.

    The PyInstaller backend ships ``ms-playwright/`` inside its data root
    (``sys._MEIPASS``); without this, Playwright would look for browsers under the
    user's home and find none on a clean machine. ``setdefault`` keeps an explicit
    user override working.
    """
    if not getattr(sys, "frozen", False):
        return
    browsers = Path(sys._MEIPASS) / "ms-playwright"  # type: ignore[attr-defined]
    if browsers.exists():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="reactions.backend", description=__doc__)
    parser.add_argument(
        "--parent-pid",
        type=int,
        default=None,
        help="Exit within ~5s after this process id dies (Electron passes its own pid).",
    )
    parser.add_argument(
        "--host",
        default=_HOST,
        help="Interface to bind (default 127.0.0.1; loopback-only by design).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _apply_frozen_env()
    port = free_port(args.host)
    token = make_token()

    if args.parent_pid is not None:
        threading.Thread(
            target=watch_parent, args=(args.parent_pid,), name="maknassa-watchdog", daemon=True
        ).start()

    app = create_app(token)
    # Announce the port/token only once we're committed to serving on them.
    print_handshake(port, token)
    uvicorn.run(app, host=args.host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
