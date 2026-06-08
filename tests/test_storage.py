"""Round-trip tests for SQLiteStore against a temporary database.

Replaces the storage test deleted in the comment-scraper -> reaction-scraper
rewrite; covers session lifecycle, reactor upsert/dedup, blocked-state marking,
and filtered fetches.
"""

from __future__ import annotations

from reactions.models import ReactorRecord, SessionStats
from reactions.storage import SQLiteStore, build_fetch_query

POST_URL = "https://www.facebook.com/some.page/posts/42"


def _record(key: str, name: str, reaction: str = "angry") -> ReactorRecord:
    return ReactorRecord(
        profile_id=key,
        profile_key=key,
        name=name,
        profile_url=f"https://www.facebook.com/{key}",
        reaction_type=reaction,
        post_url=POST_URL,
    )


def _store(tmp_path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "reactions.db")


def test_build_fetch_query_is_pure():
    """The extracted query builder needs no DB and no connection."""
    sql, params = build_fetch_query(
        POST_URL, reaction_types=["angry", "haha"], names=["Ann"], only_blocked=True
    )
    assert "reaction_type IN (?, ?)" in sql
    assert "name LIKE ?" in sql
    assert "blocked = 1" in sql
    assert params == [POST_URL, "angry", "haha", "%Ann%"]


def test_build_fetch_query_default_hides_blocked():
    sql, params = build_fetch_query(POST_URL)
    assert "blocked = 0" in sql
    assert params == [POST_URL]


def test_upsert_is_insert_then_duplicate(tmp_path):
    store = _store(tmp_path)
    sid = store.start_session(POST_URL, tmp_path, headless=False)

    assert store.upsert_reactor(sid, _record("1", "Ann")) is True  # newly inserted
    assert store.upsert_reactor(sid, _record("1", "Ann (edited)")) is False  # conflict -> update

    rows = store.fetch_reactors(POST_URL)
    assert len(rows) == 1
    assert rows[0].name == "Ann (edited)"  # metadata refreshed on conflict


def test_mark_blocked_then_filtered_fetch(tmp_path):
    store = _store(tmp_path)
    sid = store.start_session(POST_URL, tmp_path, headless=False)
    store.upsert_reactor(sid, _record("1", "Ann"))
    store.upsert_reactor(sid, _record("2", "Bob"))

    store.mark_blocked(POST_URL, "1")

    # Default fetch hides blocked rows.
    unblocked = store.fetch_reactors(POST_URL)
    assert {r.profile_key for r in unblocked} == {"2"}

    only_blocked = store.fetch_reactors(POST_URL, only_blocked=True)
    assert [r.profile_key for r in only_blocked] == ["1"]
    assert only_blocked[0].blocked is True

    # Unblocking restores it to the default view.
    store.mark_unblocked(POST_URL, "1")
    assert {r.profile_key for r in store.fetch_reactors(POST_URL)} == {"1", "2"}


def test_fetch_filters_by_reaction_and_name(tmp_path):
    store = _store(tmp_path)
    sid = store.start_session(POST_URL, tmp_path, headless=False)
    store.upsert_reactor(sid, _record("1", "Ann", reaction="angry"))
    store.upsert_reactor(sid, _record("2", "Bob", reaction="haha"))
    store.upsert_reactor(sid, _record("3", "Annie", reaction="angry"))

    by_type = store.fetch_reactors(POST_URL, reaction_types=["angry"])
    assert {r.profile_key for r in by_type} == {"1", "3"}

    by_name = store.fetch_reactors(POST_URL, names=["Ann"])  # LIKE %Ann%
    assert {r.profile_key for r in by_name} == {"1", "3"}


def test_finish_session_persists_status_and_counts(tmp_path):
    store = _store(tmp_path)
    sid = store.start_session(POST_URL, tmp_path, headless=False)
    stats = SessionStats(discovered_rows=5, stored_reactors=3, duplicate_reactors=2)
    stats.per_type_counts = {"angry": 3}

    store.finish_session(sid, "completed", stats, notes="done")

    with store.connect() as conn:
        row = conn.execute(
            "SELECT status, stored_reactors, finished_at, per_type_json, notes "
            "FROM reaction_sessions WHERE id = ?",
            (sid,),
        ).fetchone()
    assert row["status"] == "completed"
    assert row["stored_reactors"] == 3
    assert row["finished_at"] is not None
    assert row["notes"] == "done"
    assert "angry" in row["per_type_json"]
