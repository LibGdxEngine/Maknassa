"""Lemon Squeezy licence gate for the desktop app.

The app is sold as a licensed download (one Facebook account per buyer, run on the
buyer's own machine). This module activates a licence key against Lemon Squeezy's
public License API, binds it to this machine, and persists a small token so the
app keeps working offline within a grace window.

Design notes
------------
* **No new dependency** -- talks to the API with stdlib ``urllib``.
* **Machine binding**: an ``instance`` is registered per machine (a stable,
  non-reversible id) so one key can't be shared across unlimited installs.
* **Offline tolerance**: after a successful online validation the app trusts the
  cached token for ``GRACE_DAYS`` before it must re-validate online again. (Lemon
  Squeezy validation is online/HMAC; true offline-crypto licences would need a
  provider like Keygen -- out of scope for the MVP.)
* **Dev bypass**: ``MAKNASSA_DEV=1`` skips the gate entirely for local work.

The licence-key endpoints are keyed by the licence key itself and need no API
secret, so nothing sensitive is embedded in the client.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from reactions import paths

# Public Lemon Squeezy License API (overridable for tests).
API_BASE = os.environ.get("MAKNASSA_LS_API", "https://api.lemonsqueezy.com/v1/licenses")
DEV_BYPASS_ENV = "MAKNASSA_DEV"
GRACE_DAYS = 7
# Re-validate online at most this often when we're already activated and online.
RECHECK_DAYS = 1
_INSTANCE_NAME = "Maknassa"
_TIMEOUT_S = 15


@dataclass
class LicenseStatus:
    activated: bool
    detail: str
    key_masked: str | None = None
    last_validated_at: str | None = None


# --------------------------------------------------------------------------- #
# Machine identity + token persistence
# --------------------------------------------------------------------------- #
def machine_id() -> str:
    """A stable, non-reversible per-machine id used as the LS instance name."""
    raw = f"{uuid.getnode()}|{platform.system()}|{platform.node()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _load_token() -> dict:
    path = paths.license_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_token(token: dict) -> None:
    paths.license_path().write_text(json.dumps(token, indent=2))


def _clear_token() -> None:
    path = paths.license_path()
    if path.exists():
        path.unlink()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# HTTP (stdlib; factored out so tests can monkeypatch it)
# --------------------------------------------------------------------------- #
def _post(endpoint: str, payload: dict) -> dict:
    """POST form-encoded params to ``{API_BASE}/{endpoint}`` and return JSON.

    Raises ``urllib.error.URLError`` on a network failure (no connectivity);
    callers treat that distinctly from an API "invalid" response.
    """
    data = urllib.parse.urlencode(payload).encode()
    request = urllib.request.Request(
        f"{API_BASE}/{endpoint}",
        data=data,
        headers={"Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:  # 4xx/5xx still carry a JSON body
        try:
            return json.loads(exc.read().decode())
        except (json.JSONDecodeError, OSError):
            return {"valid": False, "activated": False, "error": f"HTTP {exc.code}"}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def is_dev_bypass() -> bool:
    return os.environ.get(DEV_BYPASS_ENV) == "1"


def activate(key: str) -> LicenseStatus:
    """Activate ``key`` for this machine and persist the token on success."""
    key = key.strip()
    if not key:
        return LicenseStatus(False, "No licence key provided.")
    try:
        result = _post("activate", {"license_key": key, "instance_name": _machine_instance()})
    except urllib.error.URLError:
        return LicenseStatus(False, "Could not reach the licence server. Check your connection.")

    if not result.get("activated"):
        return LicenseStatus(False, result.get("error") or "Activation failed (invalid or used-up key).")

    instance = result.get("instance") or {}
    token = {
        "license_key": key,
        "instance_id": instance.get("id"),
        "instance_name": instance.get("name", _machine_instance()),
        "last_validated_at": _now().isoformat(),
        "status": (result.get("license_key") or {}).get("status", "active"),
    }
    _save_token(token)
    return LicenseStatus(True, "Licence activated.", _mask(key), token["last_validated_at"])


def validate(force: bool = False) -> bool:
    """Validate the stored licence online; refresh the cached timestamp on success.

    Returns True when the key is valid. On a network error, falls back to the
    offline grace window (so a brief outage doesn't lock the buyer out).
    """
    token = _load_token()
    key, instance_id = token.get("license_key"), token.get("instance_id")
    if not key:
        return False
    if not force and _within_recheck(token):
        return True
    try:
        result = _post("validate", {"license_key": key, "instance_id": instance_id or ""})
    except urllib.error.URLError:
        return _within_grace(token)

    if result.get("valid"):
        token["last_validated_at"] = _now().isoformat()
        token["status"] = (result.get("license_key") or {}).get("status", "active")
        _save_token(token)
        return True
    # An explicit "invalid" (revoked/refunded/expired) clears the token.
    _clear_token()
    return False


def is_activated() -> bool:
    """True when the app should run: dev bypass, or a valid/grace-period licence."""
    if is_dev_bypass():
        return True
    token = _load_token()
    if not token.get("license_key"):
        return False
    if _within_recheck(token):
        return True
    # Past the recheck interval -- try online, but tolerate offline within grace.
    return validate()


def deactivate() -> bool:
    """Release this machine's activation (frees a seat) and clear the token."""
    token = _load_token()
    key, instance_id = token.get("license_key"), token.get("instance_id")
    if not key:
        return False
    try:
        _post("deactivate", {"license_key": key, "instance_id": instance_id or ""})
    except urllib.error.URLError:
        pass  # best-effort; still clear locally
    _clear_token()
    return True


def status() -> LicenseStatus:
    """Human-facing status for the CLI ``license status`` command."""
    if is_dev_bypass():
        return LicenseStatus(True, f"Dev bypass active ({DEV_BYPASS_ENV}=1).")
    token = _load_token()
    if not token.get("license_key"):
        return LicenseStatus(False, "Not activated. Run `maknassa license activate <key>`.")
    activated = is_activated()
    detail = "Licence active." if activated else "Licence invalid or expired."
    return LicenseStatus(
        activated,
        detail,
        _mask(token["license_key"]),
        token.get("last_validated_at"),
    )


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #
def _machine_instance() -> str:
    return f"{_INSTANCE_NAME}-{machine_id()}"


def _mask(key: str) -> str:
    return f"{key[:4]}…{key[-4:]}" if len(key) > 8 else "…"


def _within_grace(token: dict) -> bool:
    ts = _parse_ts(token.get("last_validated_at"))
    return ts is not None and _now() - ts < timedelta(days=GRACE_DAYS)


def _within_recheck(token: dict) -> bool:
    ts = _parse_ts(token.get("last_validated_at"))
    return ts is not None and _now() - ts < timedelta(days=RECHECK_DAYS)
