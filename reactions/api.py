"""Localhost HTTP API over the reactions core, consumed by the Electron frontend.

The desktop app is split in two: an Electron shell renders the UI, and this
FastAPI sidecar wraps the existing Playwright core (login / fetch / block /
unblock). They speak over loopback HTTP so the renderer never imports Python and
the Python never owns a window -- the same separation the old Streamlit build had
between its script thread and ``ui_fetch.in_thread``, made explicit as a process
boundary.

Why the shape here looks the way it does:

* **Token auth, not CORS.** A loopback server is still reachable by any local
  process and any web page the user visits (DNS-rebinding / localhost fetch), so
  every ``/api/*`` route except the unauthenticated health probe requires the
  ``X-Maknassa-Token`` header to match the secret the backend printed on its
  handshake line. Only the Electron main process, which spawned us and read that
  line, knows it.

* **One browser job at a time.** The core drives a single persistent Chromium
  profile (the user's Facebook login). Two concurrent sessions would fight over
  that profile dir, so the job manager admits exactly one running browser job and
  answers 409 ``busy`` to any overlap -- the API twin of the Streamlit app, which
  froze its whole session while a browser action ran.

* **Each job on a fresh thread.** Playwright's *sync* API raises if it starts on a
  thread that already owns a running asyncio loop, and uvicorn's worker threads
  do. So every job body runs via :func:`reactions.ui_fetch.in_thread`, which hops
  to a brand-new loop-less thread -- the exact reason that helper exists.

* **Settings persisted as JSON.** ``GET/PUT /api/settings`` and the post-login
  ``account_id`` live in ``app_data_dir()/ui_state.json`` so the choices the user
  made (profile dir, headless, pacing, stop-after) and their connected identity
  survive a restart. A missing or corrupt file degrades to defaults rather than
  crashing the backend on first run.

Browser jobs build their :class:`~reactions.config.ReactionConfig` from the saved
settings *at submission time* via :func:`reactions.service.session_config`, with
login forced headed (you cannot sign in to a headless window) exactly as the old
``_do_login`` did.

The core entry points are imported as *module attributes* (``fetch_reactors``,
``login_flow``, ``FacebookBlocker``, ...) precisely so tests can monkeypatch
``reactions.api.<seam>`` and exercise the whole job lifecycle without a browser.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import threading
import uuid
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from reactions import paths
from reactions.browser import login_flow
from reactions.service import FacebookBlocker, session_config
from reactions.ui_fetch import fetch_reactors, in_thread

logger = logging.getLogger(__name__)

# Imported as module attributes above so tests can monkeypatch reactions.api.<seam>
# (fetch_reactors / login_flow / FacebookBlocker) and drive the job lifecycle with
# stubs -- no real Chromium, no Facebook. Listed here as the public seam contract.
__all__ = ["create_app", "fetch_reactors", "login_flow", "FacebookBlocker", "session_config"]

TOKEN_HEADER = "X-Maknassa-Token"
_STATE_FILENAME = "ui_state.json"

# Default UI settings, merged over whatever ui_state.json holds. profile_dir is
# resolved lazily (paths.default_profile_dir() touches the data dir) so importing
# this module never creates folders -- only a GET/PUT does.
_DEFAULT_SETTINGS: dict[str, Any] = {
    "headless": False,
    "min_delay": 2.0,
    "max_delay": 6.0,
    "stop_after": 0,
}


# --------------------------------------------------------------------------- #
# Persisted UI state (settings + connected account) at app_data_dir/ui_state.json
# --------------------------------------------------------------------------- #
def _state_path() -> Path:
    return paths.app_data_dir() / _STATE_FILENAME


def _load_state() -> dict[str, Any]:
    """Read ui_state.json, tolerating a missing or corrupt file (-> empty dict).

    First run has no file; a half-written or hand-mangled file must not take the
    backend down, so any read/parse error degrades to "no saved state" and the
    callers fall back to defaults.
    """
    try:
        raw = _state_path().read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("ui_state.json is corrupt; ignoring it and using defaults")
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state: dict[str, Any]) -> None:
    """Persist ``state`` to ui_state.json (the data dir is created on demand)."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _current_settings() -> dict[str, Any]:
    """The effective settings: saved values merged over the defaults.

    ``profile_dir`` defaults to ``paths.default_profile_dir()`` when unset so a
    fresh install has a sensible location without the user touching settings.
    """
    state = _load_state()
    settings = dict(_DEFAULT_SETTINGS)
    settings["profile_dir"] = str(paths.default_profile_dir())
    for key in ("profile_dir", "headless", "min_delay", "max_delay", "stop_after"):
        if key in state:
            settings[key] = state[key]
    return _coerce_settings(settings)


def _coerce_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Normalize types so the JSON contract is stable regardless of input source."""
    return {
        "profile_dir": str(settings["profile_dir"]),
        "headless": bool(settings["headless"]),
        "min_delay": float(settings["min_delay"]),
        "max_delay": float(settings["max_delay"]),
        "stop_after": int(settings["stop_after"]),
    }


# --------------------------------------------------------------------------- #
# Serialization helpers: the core mixes pydantic models (UIReactor / FetchResult)
# with dataclasses (BlockOutcome), so jsonify normalizes both to plain dicts.
# --------------------------------------------------------------------------- #
def _jsonify(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, list):
        return [_jsonify(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonify(item) for key, item in value.items()}
    return value


# --------------------------------------------------------------------------- #
# Job manager: one running browser job at a time, each on a fresh (loop-less)
# thread so sync Playwright is safe.
# --------------------------------------------------------------------------- #
class Job:
    """A single browser task and its live state, polled via GET /api/jobs/{id}.

    ``progress`` is a mutable dict the worker updates in place (block/unblock push
    per-item ``done``/``total``/``outcomes`` into it); the poll endpoint snapshots
    it. ``cancel_requested`` is a flag the block/unblock loop honors *between*
    items -- fetch and login run to completion, since a half-fetch or a partial
    login has nothing to cancel cleanly.
    """

    def __init__(self, kind: str) -> None:
        self.id = uuid.uuid4().hex
        self.kind = kind
        self.state = "running"  # running | done | error | cancelled
        self.progress: dict[str, Any] = {}
        self.result: Any = None
        self.error: str | None = None
        self.cancel_requested = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "state": self.state,
            "progress": _jsonify(self.progress),
            "result": _jsonify(self.result),
            "error": self.error,
        }


class JobManager:
    """Owns the job registry and enforces the single-running-browser-job rule.

    A lock guards the registry and the "is a job already running?" check so two
    near-simultaneous POSTs can't both pass the busy gate. The work itself runs
    outside the lock (on its own thread) so polling stays responsive.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._running_id: str | None = None

    def running_job_id(self) -> str | None:
        with self._lock:
            return self._running_id

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def request_cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            job.cancel_requested = True
            return True

    def submit(self, kind: str, work: Callable[[Job], Any]) -> Job | str:
        """Register and start a browser job, or return the busy job id on conflict.

        ``work(job)`` runs on a fresh loop-less thread (via ``in_thread``) so sync
        Playwright is safe; its return value becomes ``job.result``. Any exception
        flips the job to ``error`` (or ``cancelled`` if cancel was requested) and
        records the message. The running slot is always released in ``finally``.
        """
        with self._lock:
            if self._running_id is not None:
                return self._running_id
            job = Job(kind)
            self._jobs[job.id] = job
            self._running_id = job.id

        def runner() -> None:
            try:
                job.result = in_thread(work, job)
                job.state = "cancelled" if job.cancel_requested else "done"
            except Exception as exc:  # noqa: BLE001 - surfaced to the client as job error
                logger.warning("%s job %s failed: %s", kind, job.id, exc)
                job.error = str(exc)
                job.state = "cancelled" if job.cancel_requested else "error"
            finally:
                with self._lock:
                    self._running_id = None

        threading.Thread(target=runner, name=f"maknassa-job-{kind}", daemon=True).start()
        return job


# --------------------------------------------------------------------------- #
# Browser work bodies (run on the job thread). Each takes the live Job so it can
# stream progress and honor cancellation.
# --------------------------------------------------------------------------- #
def _settings_config(settings: dict[str, Any], post_url: str = "", *, force_headed: bool = False):
    """Build a ReactionConfig from saved settings via service.session_config.

    ``stop_after`` maps onto ``session_config``'s ``daily_cap`` (its per-run cap;
    0 = unlimited). ``force_headed`` overrides headless for login, which cannot be
    completed in a headless window -- the same override the old ``_do_login`` used.
    post_url is threaded through for the fetch path (session_config builds a
    by-URL config with an empty post_url, so we set it afterward).
    """
    config = session_config(
        settings["profile_dir"],
        headless=False if force_headed else settings["headless"],
        min_delay_s=settings["min_delay"],
        max_delay_s=settings["max_delay"],
        daily_cap=settings["stop_after"],
    )
    if post_url:
        config.post_url = post_url
    return config


def _run_login(job: Job, timeout_s: int) -> dict[str, Any]:
    """Open a headed login window, wait for sign-in, and persist the account id.

    ``login_flow`` returns the Facebook ``c_user`` id on success or ``None`` on
    timeout. A timeout is surfaced as an *error* job (``login-timeout``) per the
    API contract; success stashes ``account_id`` in ui_state.json so a later
    GET /api/session reports ``connected: true`` across restarts.
    """
    settings = _current_settings()
    config = _settings_config(settings, force_headed=True)
    account_id = login_flow(config, timeout_s=timeout_s)
    if not account_id:
        raise RuntimeError("login-timeout")
    state = _load_state()
    state["account_id"] = account_id
    _save_state(state)
    return {"account_id": account_id}


def _run_fetch(job: Job, post_url: str) -> dict[str, Any]:
    """Fetch the post's reactors and return the serialized FetchResult.

    Runs to completion (no mid-fetch cancel): the result carries the reactor list
    and Facebook's own ``expected_total`` so the UI can flag an undercount.
    """
    settings = _current_settings()
    config = _settings_config(settings, post_url=post_url)
    result = fetch_reactors(config)
    return {"reactors": _jsonify(result.reactors), "expected_total": result.expected_total}


def _run_block(job: Job, profile_urls: list[str], *, unblock: bool) -> list[Any]:
    """Block/unblock each profile in ONE persistent session, streaming progress.

    Uses ``FacebookBlocker`` item-by-item (one browser session for the whole
    batch, like ``block_urls``/``run_batch``) so each outcome is appended to
    ``job.progress['outcomes']`` and ``done``/``total`` tick up as the UI polls --
    a per-profile progress feed the batch helpers can't give (they return only the
    final list). It replicates ``run_batch``'s safety semantics: the human pause
    between *successful* actions, ``stop_after`` as a per-run cap (0 = unlimited),
    and the cancel flag checked *between* items.
    """
    settings = _current_settings()
    config = _settings_config(settings)
    cap = config.daily_cap if config.daily_cap > 0 else 0

    total = len(profile_urls)
    outcomes: list[Any] = []
    job.progress.update({"done": 0, "total": total, "outcomes": outcomes})

    succeeded = 0
    with FacebookBlocker(
        settings["profile_dir"],
        headless=settings["headless"],
        min_delay_s=settings["min_delay"],
        max_delay_s=settings["max_delay"],
    ) as blocker:
        action = blocker.unblock if unblock else blocker.block
        for index, url in enumerate(profile_urls):
            if job.cancel_requested:
                break
            if cap and succeeded >= cap:
                logger.info("stop_after cap of %d reached; stopping", cap)
                break
            outcome = action(url)
            outcomes.append(_jsonify(outcome))
            job.progress["done"] = index + 1
            last = index == total - 1
            if outcome.status in ("blocked", "unblocked"):
                succeeded += 1
                # Pause between successes to stay human-paced (mirrors run_batch):
                # skip the wait on the final item, after the cap, and on cancel.
                if not last and not (cap and succeeded >= cap) and not job.cancel_requested:
                    from reactions.service import human_delay

                    human_delay(config)
    return outcomes


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class SettingsBody(BaseModel):
    """Partial settings update; any omitted field keeps its saved value."""

    profile_dir: str | None = None
    headless: bool | None = None
    min_delay: float | None = None
    max_delay: float | None = None
    stop_after: int | None = None


class LoginBody(BaseModel):
    timeout_s: int = 300


class FetchBody(BaseModel):
    post_url: str


class ProfileUrlsBody(BaseModel):
    profile_urls: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------- #
def create_app(token: str) -> FastAPI:
    """Build the FastAPI app guarding ``/api/*`` (except health) with ``token``.

    The app owns a single :class:`JobManager`, so the one-browser-job rule holds
    for the lifetime of the process. ``token`` is the secret the backend printed on
    its handshake line; the Electron main process echoes it in ``X-Maknassa-Token``
    on every request.
    """
    app = FastAPI(title="Maknassa Backend", docs_url=None, redoc_url=None, openapi_url=None)
    jobs = JobManager()

    def require_token(x_maknassa_token: str | None = Header(default=None)) -> None:
        if x_maknassa_token != token:
            # Raise via a sentinel the handler converts to a clean 401 body. We use
            # a plain exception rather than HTTPException so the body matches the
            # frozen {"error":"unauthorized"} contract exactly.
            raise _Unauthorized()

    auth = [Depends(require_token)]

    def _busy_or_submit(kind: str, work: Callable[[Job], Any]) -> JSONResponse:
        outcome = jobs.submit(kind, work)
        if isinstance(outcome, str):  # a job is already running -> 409 busy
            return JSONResponse(
                status_code=409, content={"error": "busy", "job_id": outcome}
            )
        return JSONResponse(status_code=202, content={"job_id": outcome.id})

    @app.exception_handler(_Unauthorized)
    async def _unauthorized_handler(_request: Request, _exc: _Unauthorized) -> JSONResponse:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        try:
            version = metadata.version("maknassa")
        except metadata.PackageNotFoundError:
            version = "dev"
        return {"status": "ok", "version": version}

    @app.get("/api/session", dependencies=auth)
    def session() -> dict[str, Any]:
        state = _load_state()
        account_id = state.get("account_id")
        return {
            "connected": bool(account_id),
            "account_id": account_id,
            "default_profile_dir": str(paths.default_profile_dir()),
            "data_dir": str(paths.app_data_dir()),
        }

    @app.get("/api/settings", dependencies=auth)
    def get_settings() -> dict[str, Any]:
        return _current_settings()

    @app.put("/api/settings", dependencies=auth)
    def put_settings(body: SettingsBody) -> dict[str, Any]:
        state = _load_state()
        updates = body.model_dump(exclude_none=True)
        merged = _current_settings()
        merged.update(updates)
        merged = _coerce_settings(merged)
        # Persist only the settings keys (never clobber account_id, which lives in
        # the same file but is owned by the login flow).
        for key in ("profile_dir", "headless", "min_delay", "max_delay", "stop_after"):
            state[key] = merged[key]
        _save_state(state)
        return merged

    @app.post("/api/login", dependencies=auth)
    def post_login(body: LoginBody) -> JSONResponse:
        return _busy_or_submit("login", lambda job: _run_login(job, body.timeout_s))

    @app.post("/api/fetch", dependencies=auth)
    def post_fetch(body: FetchBody) -> JSONResponse:
        return _busy_or_submit("fetch", lambda job: _run_fetch(job, body.post_url))

    @app.post("/api/block", dependencies=auth)
    def post_block(body: ProfileUrlsBody) -> JSONResponse:
        return _busy_or_submit(
            "block", lambda job: _run_block(job, body.profile_urls, unblock=False)
        )

    @app.post("/api/unblock", dependencies=auth)
    def post_unblock(body: ProfileUrlsBody) -> JSONResponse:
        return _busy_or_submit(
            "unblock", lambda job: _run_block(job, body.profile_urls, unblock=True)
        )

    @app.get("/api/jobs/{job_id}", dependencies=auth)
    def get_job(job_id: str) -> JSONResponse:
        job = jobs.get(job_id)
        if job is None:
            return JSONResponse(status_code=404, content={"error": "not-found"})
        return JSONResponse(status_code=200, content=job.snapshot())

    @app.post("/api/jobs/{job_id}/cancel", dependencies=auth)
    def cancel_job(job_id: str) -> JSONResponse:
        if not jobs.request_cancel(job_id):
            return JSONResponse(status_code=404, content={"error": "not-found"})
        return JSONResponse(status_code=200, content={"cancelled": True})

    return app


class _Unauthorized(Exception):
    """Internal signal -> a 401 {"error":"unauthorized"} response via the handler."""
