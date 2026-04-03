import sqlite3
import tempfile
import unittest
from pathlib import Path

from scraper.models import CommentRecord, SessionStats
from scraper.storage import SQLiteStore


class SQLiteStoreTests(unittest.TestCase):
    def test_upsert_and_finish_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "comments.db"
            store = SQLiteStore(db_path)
            session_id = store.start_session(
                post_url="https://www.facebook.com/example/posts/1",
                auth_mode="persistent_profile",
                profile_dir=Path(tmpdir) / "profile",
                headless=False,
            )
            store.update_session_context(
                session_id,
                canonical_post_url="https://www.facebook.com/example/posts/1?comment_id=1",
                page_locale="ar",
                logged_out=True,
                filtered_comments_notice=True,
                visible_comment_anchors=3,
                expansion_clicks=1,
                unmatched_expand_controls=2,
                sort_switch_attempted=True,
                sort_switch_succeeded=True,
                initial_sort_label="الأكثر ملاءمة",
                final_sort_label="كل التعليقات",
                visible_comment_anchors_before_sort=3,
                visible_comment_anchors_after_sort=5,
                filtered_comments_notice_before_sort=True,
                filtered_comments_notice_after_sort=False,
            )
            stored = store.upsert_comment(
                session_id,
                CommentRecord(
                    comment_id="1",
                    parent_comment_id=None,
                    depth=0,
                    author_name="Author",
                    author_profile_url="https://www.facebook.com/author",
                    author_thumbnail_url="https://www.facebook.com/avatar.jpg",
                    text="Hello",
                    timestamp_text="1h",
                    permalink="https://www.facebook.com/example/posts/1?comment_id=1",
                ),
            )
            self.assertTrue(stored)
            store.finish_session(
                session_id,
                "completed",
                SessionStats(
                    discovered_nodes=1,
                    stored_comments=1,
                    visible_comment_anchors=3,
                    expansion_clicks=1,
                    unmatched_expand_controls=2,
                ),
            )
            connection = sqlite3.connect(db_path)
            try:
                comment_count = connection.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
                session_row = connection.execute(
                    """
                    SELECT status, canonical_post_url, page_locale, logged_out,
                           filtered_comments_notice, visible_comment_anchors,
                           expansion_clicks, unmatched_expand_controls,
                           sort_switch_attempted, sort_switch_succeeded,
                           initial_sort_label, final_sort_label,
                           visible_comment_anchors_before_sort, visible_comment_anchors_after_sort,
                           filtered_comments_notice_before_sort, filtered_comments_notice_after_sort
                    FROM scrape_sessions WHERE id = ?
                    """,
                    (session_id,),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(comment_count, 1)
            self.assertEqual(session_row[0], "completed")
            self.assertEqual(session_row[1], "https://www.facebook.com/example/posts/1?comment_id=1")
            self.assertEqual(session_row[2], "ar")
            self.assertEqual(session_row[3], 1)
            self.assertEqual(session_row[4], 1)
            self.assertEqual(session_row[5], 3)
            self.assertEqual(session_row[6], 1)
            self.assertEqual(session_row[7], 2)
            self.assertEqual(session_row[8], 1)
            self.assertEqual(session_row[9], 1)
            self.assertEqual(session_row[10], "الأكثر ملاءمة")
            self.assertEqual(session_row[11], "كل التعليقات")
            self.assertEqual(session_row[12], 3)
            self.assertEqual(session_row[13], 5)
            self.assertEqual(session_row[14], 1)
            self.assertEqual(session_row[15], 0)


if __name__ == "__main__":
    unittest.main()
