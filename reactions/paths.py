"""Per-user, writable filesystem locations for app data, profiles, and licence.

Run from a source checkout, the app historically wrote ``reactions.db`` and
``.profiles/facebook`` relative to the current directory. Once frozen into a
PyInstaller bundle the working directory is read-only, so all mutable state must
live under the OS's per-user data dir instead. This module is the single source
of truth for those locations (via ``platformdirs``); the CLI and Streamlit UI
seed their path defaults from here.

Layout (Linux ``~/.local/share/Maknassa`` / macOS ``~/Library/Application
Support/Maknassa`` / Windows ``%LOCALAPPDATA%\\Maknassa``)::

    <app_data_dir>/data/reactions.db        # SQLite store
    <app_data_dir>/profiles/<account>/      # Playwright persistent profile(s)
    <config_dir>/license.json               # activation token

Set ``MAKNASSA_DATA_DIR`` to relocate everything under one folder (portable
install / tests); when set, config lives at ``<MAKNASSA_DATA_DIR>/config``.
"""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

APP_NAME = "Maknassa"
APP_AUTHOR = "Maknassa"

# Override env var: when set, app data and config both live under this root.
DATA_DIR_ENV = "MAKNASSA_DATA_DIR"


def _override_root() -> Path | None:
    raw = os.environ.get(DATA_DIR_ENV)
    return Path(raw).expanduser() if raw else None


def app_data_dir() -> Path:
    """Writable root for the database and browser profiles (created on demand)."""
    base = _override_root() or Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_dir() -> Path:
    """Writable root for small config/state like the licence token."""
    override = _override_root()
    base = (override / "config") if override else Path(
        platformdirs.user_config_dir(APP_NAME, APP_AUTHOR)
    )
    base.mkdir(parents=True, exist_ok=True)
    return base


def default_db_path() -> Path:
    """Default SQLite path. ``SQLiteStore`` creates the ``data/`` parent itself."""
    return app_data_dir() / "data" / "reactions.db"


def default_profile_dir(account: str = "facebook") -> Path:
    """Default persistent-profile dir for an account (Playwright creates it)."""
    return app_data_dir() / "profiles" / account


def license_path() -> Path:
    """Path to the persisted licence-activation token."""
    return config_dir() / "license.json"
