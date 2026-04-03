from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from scraper.models import CommentRecord, SessionStats


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteStore:
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

                CREATE TABLE IF NOT EXISTS scrape_sessions (
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
                    filtered_comments_notice INTEGER,
                    visible_comment_anchors INTEGER NOT NULL DEFAULT 0,
                    expansion_clicks INTEGER NOT NULL DEFAULT 0,
                    unmatched_expand_controls INTEGER NOT NULL DEFAULT 0,
                    sort_switch_attempted INTEGER,
                    sort_switch_succeeded INTEGER,
                    initial_sort_label TEXT,
                    final_sort_label TEXT,
                    visible_comment_anchors_before_sort INTEGER,
                    visible_comment_anchors_after_sort INTEGER,
                    filtered_comments_notice_before_sort INTEGER,
                    filtered_comments_notice_after_sort INTEGER,
                    debug_dir TEXT,
                    status TEXT NOT NULL,
                    discovered_nodes INTEGER NOT NULL DEFAULT 0,
                    stored_comments INTEGER NOT NULL DEFAULT 0,
                    duplicate_comments INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    comment_id TEXT,
                    parent_comment_id TEXT,
                    depth INTEGER NOT NULL,
                    author_name TEXT,
                    author_profile_url TEXT,
                    author_thumbnail_url TEXT,
                    text TEXT,
                    timestamp_text TEXT,
                    permalink TEXT,
                    seen_at TEXT NOT NULL,
                    raw_dedupe_key TEXT,
                    FOREIGN KEY(session_id) REFERENCES scrape_sessions(id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_comments_comment_id
                ON comments(comment_id);

                CREATE INDEX IF NOT EXISTS idx_comments_session_id
                ON comments(session_id);

                CREATE TABLE IF NOT EXISTS failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    target TEXT,
                    error_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES scrape_sessions(id)
                );
                """
            )
            self._ensure_column(connection, "scrape_sessions", "canonical_post_url", "TEXT")
            self._ensure_column(connection, "scrape_sessions", "page_locale", "TEXT")
            self._ensure_column(connection, "scrape_sessions", "logged_out", "INTEGER")
            self._ensure_column(connection, "scrape_sessions", "filtered_comments_notice", "INTEGER")
            self._ensure_column(connection, "scrape_sessions", "visible_comment_anchors", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "scrape_sessions", "expansion_clicks", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "scrape_sessions", "unmatched_expand_controls", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "scrape_sessions", "sort_switch_attempted", "INTEGER")
            self._ensure_column(connection, "scrape_sessions", "sort_switch_succeeded", "INTEGER")
            self._ensure_column(connection, "scrape_sessions", "initial_sort_label", "TEXT")
            self._ensure_column(connection, "scrape_sessions", "final_sort_label", "TEXT")
            self._ensure_column(connection, "scrape_sessions", "visible_comment_anchors_before_sort", "INTEGER")
            self._ensure_column(connection, "scrape_sessions", "visible_comment_anchors_after_sort", "INTEGER")
            self._ensure_column(connection, "scrape_sessions", "filtered_comments_notice_before_sort", "INTEGER")
            self._ensure_column(connection, "scrape_sessions", "filtered_comments_notice_after_sort", "INTEGER")
            self._ensure_column(connection, "scrape_sessions", "debug_dir", "TEXT")

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column in existing:
            return
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def start_session(
        self,
        post_url: str,
        auth_mode: str,
        profile_dir: Path,
        headless: bool,
        debug_dir: Path | None = None,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO scrape_sessions (
                    post_url, started_at, auth_mode, profile_dir, headless, debug_dir, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (post_url, utcnow_iso(), auth_mode, str(profile_dir), int(headless), str(debug_dir) if debug_dir else None, "running"),
            )
            return int(cursor.lastrowid)

    def update_session_context(self, session_id: int, **fields: Any) -> None:
        assignments = []
        values = []
        for key, value in fields.items():
            if value is None:
                continue
            assignments.append(f"{key} = ?")
            if isinstance(value, bool):
                values.append(int(value))
            else:
                values.append(value)
        if not assignments:
            return
        values.append(session_id)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE scrape_sessions SET {', '.join(assignments)} WHERE id = ?",
                values,
            )

    def finish_session(self, session_id: int, status: str, stats: SessionStats, notes: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE scrape_sessions
                SET finished_at = ?,
                    status = ?,
                    discovered_nodes = ?,
                    stored_comments = ?,
                    duplicate_comments = ?,
                    failure_count = ?,
                    visible_comment_anchors = ?,
                    expansion_clicks = ?,
                    unmatched_expand_controls = ?,
                    notes = ?
                WHERE id = ?
                """,
                (
                    utcnow_iso(),
                    status,
                    stats.discovered_nodes,
                    stats.stored_comments,
                    stats.duplicate_comments,
                    stats.failures,
                    stats.visible_comment_anchors,
                    stats.expansion_clicks,
                    stats.unmatched_expand_controls,
                    notes,
                    session_id,
                ),
            )

    def record_failure(self, session_id: int, stage: str, target: str | None, error_text: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO failures (session_id, stage, target, error_text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, stage, target, error_text, utcnow_iso()),
            )

    def upsert_comment(self, session_id: int, record: CommentRecord, raw_dedupe_key: str | None = None) -> bool:
        with self.connect() as connection:
            if record.comment_id:
                cursor = connection.execute(
                    """
                    INSERT INTO comments (
                        session_id, comment_id, parent_comment_id, depth, author_name,
                        author_profile_url, author_thumbnail_url, text, timestamp_text,
                        permalink, seen_at, raw_dedupe_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(comment_id) DO UPDATE SET
                        session_id = excluded.session_id,
                        parent_comment_id = excluded.parent_comment_id,
                        depth = excluded.depth,
                        author_name = excluded.author_name,
                        author_profile_url = excluded.author_profile_url,
                        author_thumbnail_url = excluded.author_thumbnail_url,
                        text = excluded.text,
                        timestamp_text = excluded.timestamp_text,
                        permalink = excluded.permalink,
                        seen_at = excluded.seen_at,
                        raw_dedupe_key = excluded.raw_dedupe_key
                    """,
                    (
                        session_id,
                        record.comment_id,
                        record.parent_comment_id,
                        record.depth,
                        record.author_name,
                        record.author_profile_url,
                        record.author_thumbnail_url,
                        record.text,
                        record.timestamp_text,
                        record.permalink,
                        utcnow_iso(),
                        raw_dedupe_key,
                    ),
                )
                return cursor.rowcount > 0
            connection.execute(
                """
                INSERT INTO comments (
                    session_id, comment_id, parent_comment_id, depth, author_name,
                    author_profile_url, author_thumbnail_url, text, timestamp_text,
                    permalink, seen_at, raw_dedupe_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    None,
                    record.parent_comment_id,
                    record.depth,
                    record.author_name,
                    record.author_profile_url,
                    record.author_thumbnail_url,
                    record.text,
                    record.timestamp_text,
                    record.permalink,
                    utcnow_iso(),
                    raw_dedupe_key,
                ),
            )
            return True
