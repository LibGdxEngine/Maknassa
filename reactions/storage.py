from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from reactions.models import ReactorRecord, SessionStats


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteStore:
    """SQLite persistence for reaction sessions and reactor rows.

    Connection/contextmanager pattern ported from the old scraper's
    ``SQLiteStore``; schema is adapted to reactors + blocking state.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS reaction_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_url TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    auth_mode TEXT NOT NULL,
                    profile_dir TEXT NOT NULL,
                    headless INTEGER NOT NULL,
                    canonical_post_url TEXT,
                    page_locale TEXT,
                    logged_out INTEGER,
                    status TEXT NOT NULL,
                    discovered_rows INTEGER NOT NULL DEFAULT 0,
                    stored_reactors INTEGER NOT NULL DEFAULT 0,
                    duplicate_reactors INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    per_type_json TEXT,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS reactors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    post_url TEXT NOT NULL,
                    profile_key TEXT NOT NULL,
                    profile_id TEXT,
                    name TEXT,
                    profile_url TEXT,
                    reaction_type TEXT NOT NULL,
                    scraped_at TEXT NOT NULL,
                    blocked INTEGER NOT NULL DEFAULT 0,
                    blocked_at TEXT,
                    FOREIGN KEY(session_id) REFERENCES reaction_sessions(id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_reactors_post_profile
                ON reactors(post_url, profile_key);

                CREATE INDEX IF NOT EXISTS idx_reactors_session
                ON reactors(session_id);

                CREATE TABLE IF NOT EXISTS failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    stage TEXT NOT NULL,
                    target TEXT,
                    error_text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    # --- sessions ---------------------------------------------------------- #
    def start_session(
        self,
        post_url: str,
        profile_dir: Path,
        headless: bool,
        auth_mode: str = "persistent_profile",
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO reaction_sessions (
                    post_url, started_at, auth_mode, profile_dir, headless, status
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (post_url, utcnow_iso(), auth_mode, str(profile_dir), int(headless), "running"),
            )
            return int(cursor.lastrowid)

    def update_session_context(self, session_id: int, **fields: Any) -> None:
        assignments, values = [], []
        for key, value in fields.items():
            if value is None:
                continue
            assignments.append(f"{key} = ?")
            values.append(int(value) if isinstance(value, bool) else value)
        if not assignments:
            return
        values.append(session_id)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE reaction_sessions SET {', '.join(assignments)} WHERE id = ?", values
            )

    def finish_session(
        self, session_id: int, status: str, stats: SessionStats, notes: str | None = None
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE reaction_sessions
                SET finished_at = ?, status = ?, discovered_rows = ?, stored_reactors = ?,
                    duplicate_reactors = ?, failure_count = ?, per_type_json = ?, notes = ?
                WHERE id = ?
                """,
                (
                    utcnow_iso(),
                    status,
                    stats.discovered_rows,
                    stats.stored_reactors,
                    stats.duplicate_reactors,
                    stats.failures,
                    json.dumps(stats.per_type_counts, ensure_ascii=False),
                    notes,
                    session_id,
                ),
            )

    def record_failure(
        self, session_id: int | None, stage: str, target: str | None, error_text: str
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO failures (session_id, stage, target, error_text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, stage, target, error_text, utcnow_iso()),
            )

    # --- reactors ---------------------------------------------------------- #
    def upsert_reactor(self, session_id: int, record: ReactorRecord) -> bool:
        """Insert a reactor; on (post_url, profile_key) conflict refresh metadata
        but never clobber the ``blocked`` flag. Returns True when newly inserted.

        ``sqlite3`` reports ``rowcount == 1`` for both a fresh INSERT and an
        ON CONFLICT update, so we use ``INSERT OR IGNORE`` (rowcount 1 = inserted,
        0 = already present) and only then UPDATE the existing row's metadata.
        """
        now = utcnow_iso()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO reactors (
                    session_id, post_url, profile_key, profile_id, name,
                    profile_url, reaction_type, scraped_at, blocked
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    session_id,
                    record.post_url,
                    record.profile_key,
                    record.profile_id,
                    record.name,
                    record.profile_url,
                    record.reaction_type,
                    now,
                ),
            )
            if cursor.rowcount == 1:
                return True
            # Already present: refresh metadata, preserve blocked / blocked_at.
            connection.execute(
                """
                UPDATE reactors SET
                    session_id = ?,
                    profile_id = ?,
                    name = COALESCE(?, name),
                    profile_url = ?,
                    reaction_type = ?,
                    scraped_at = ?
                WHERE post_url = ? AND profile_key = ?
                """,
                (
                    session_id,
                    record.profile_id,
                    record.name,
                    record.profile_url,
                    record.reaction_type,
                    now,
                    record.post_url,
                    record.profile_key,
                ),
            )
            return False

    def fetch_reactors(
        self,
        post_url: str,
        reaction_types: list[str] | None = None,
        names: list[str] | None = None,
        include_blocked: bool = False,
        only_blocked: bool = False,
    ) -> list[ReactorRecord]:
        clauses = ["post_url = ?"]
        params: list[Any] = [post_url]
        if reaction_types:
            placeholders = ", ".join("?" for _ in reaction_types)
            clauses.append(f"reaction_type IN ({placeholders})")
            params.extend(reaction_types)
        if names:
            name_clauses = " OR ".join("name LIKE ?" for _ in names)
            clauses.append(f"({name_clauses})")
            params.extend(f"%{name}%" for name in names)
        if only_blocked:
            clauses.append("blocked = 1")
        elif not include_blocked:
            clauses.append("blocked = 0")
        query = f"SELECT * FROM reactors WHERE {' AND '.join(clauses)} ORDER BY name COLLATE NOCASE"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            ReactorRecord(
                profile_id=row["profile_id"],
                profile_key=row["profile_key"],
                name=row["name"],
                profile_url=row["profile_url"],
                reaction_type=row["reaction_type"],
                post_url=row["post_url"],
                blocked=bool(row["blocked"]),
            )
            for row in rows
        ]

    def mark_blocked(self, post_url: str, profile_key: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE reactors SET blocked = 1, blocked_at = ? WHERE post_url = ? AND profile_key = ?",
                (utcnow_iso(), post_url, profile_key),
            )

    def mark_unblocked(self, post_url: str, profile_key: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE reactors SET blocked = 0, blocked_at = NULL WHERE post_url = ? AND profile_key = ?",
                (post_url, profile_key),
            )

    def count_blocked_today(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM reactors WHERE blocked = 1 AND date(blocked_at) = date('now')"
            ).fetchone()
        return int(row["n"]) if row else 0

    def reaction_type_breakdown(self, post_url: str) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT reaction_type, COUNT(*) AS n FROM reactors WHERE post_url = ? GROUP BY reaction_type",
                (post_url,),
            ).fetchall()
        return {row["reaction_type"]: int(row["n"]) for row in rows}
