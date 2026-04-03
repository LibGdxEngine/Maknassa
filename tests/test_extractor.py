import unittest

from scraper.extractor import extract_comment_id, normalize_url, normalize_url_with_keys, parse_comment
from scraper.models import RawCommentCandidate


class ExtractorTests(unittest.TestCase):
    def test_normalize_url_keeps_comment_identity_fields(self) -> None:
        url = normalize_url(
            "/story.php?story_fbid=12&id=34&comment_id=56&notif_id=999",
            "https://www.facebook.com/example/posts/12",
        )
        self.assertEqual(url, "https://www.facebook.com/story.php?comment_id=56&story_fbid=12&id=34")

    def test_extract_comment_id_from_permalink(self) -> None:
        self.assertEqual(
            extract_comment_id("https://www.facebook.com/example/posts/123?comment_id=987654321"),
            "987654321",
        )

    def test_normalize_profile_url_drops_tracking_and_comment_query(self) -> None:
        url = normalize_url_with_keys(
            "https://www.facebook.com/author.name?comment_id=encoded&__tn__=R]-R",
            "https://www.facebook.com/example/posts/123",
            keep_query_keys=(),
        )
        self.assertEqual(url, "https://www.facebook.com/author.name")

    def test_parse_comment_uses_parent_hint_and_depth(self) -> None:
        candidate = RawCommentCandidate(
            node_key="node-1",
            outer_html="""
            <article data-commentid="999">
              <img src="/avatar.jpg" />
              <strong><a href="/author.profile">Author Name</a></strong>
              <div data-ad-preview="message">This is a nested reply</div>
              <a href="/example/posts/111?comment_id=999">4h</a>
            </article>
            """,
            depth_hint=2,
            parent_comment_id_hint="123",
            permalink_hint=None,
            author_name_hint="Author Name",
            author_profile_url_hint="/author.profile?comment_id=encoded",
            author_thumbnail_url_hint="/avatar.jpg?foo=1",
            text_hint="This is a nested reply",
            timestamp_text_hint="4h",
            source_url="https://www.facebook.com/example/posts/111",
        )
        record = parse_comment(candidate)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.comment_id, "999")
        self.assertEqual(record.parent_comment_id, "123")
        self.assertEqual(record.depth, 2)
        self.assertEqual(record.author_name, "Author Name")
        self.assertEqual(record.author_profile_url, "https://www.facebook.com/author.profile")
        self.assertEqual(record.author_thumbnail_url, "https://www.facebook.com/avatar.jpg")
        self.assertEqual(record.text, "This is a nested reply")
        self.assertEqual(record.timestamp_text, "4h")

    def test_parse_comment_prefers_timestamp_permalink_over_author_anchor(self) -> None:
        candidate = RawCommentCandidate(
            node_key="node-3",
            outer_html="""
            <div>
              <a href="/person?comment_id=Y29tbWVudDo=">Author Name</a>
              <div data-ad-preview="message">Actual comment body</div>
              <a href="/post/1?comment_id=2468">1d</a>
            </div>
            """,
            depth_hint=0,
            parent_comment_id_hint=None,
            permalink_hint="https://www.facebook.com/post/1?comment_id=2468",
            author_name_hint="Author Name",
            author_profile_url_hint="https://www.facebook.com/person?comment_id=Y29tbWVudDo=",
            text_hint="Actual comment body",
            timestamp_text_hint="1d",
            source_url="https://www.facebook.com/post/1",
        )
        record = parse_comment(candidate)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.comment_id, "2468")
        self.assertEqual(record.author_name, "Author Name")
        self.assertEqual(record.timestamp_text, "1d")
        self.assertEqual(record.text, "Actual comment body")
        self.assertEqual(record.author_profile_url, "https://www.facebook.com/person")

    def test_parse_comment_returns_none_when_no_content_found(self) -> None:
        candidate = RawCommentCandidate(
            node_key="node-2",
            outer_html="<div></div>",
            depth_hint=0,
            parent_comment_id_hint=None,
            permalink_hint=None,
            source_url="https://www.facebook.com/example/posts/111",
        )
        self.assertIsNone(parse_comment(candidate))


if __name__ == "__main__":
    unittest.main()
