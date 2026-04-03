import unittest

from scraper.browser import (
    is_all_comments_text,
    is_expand_control_text,
    is_newest_comments_text,
    is_sort_control_text,
    normalize_control_text,
)


class BrowserHelperTests(unittest.TestCase):
    def test_normalize_control_text_collapses_spacing(self) -> None:
        self.assertEqual(normalize_control_text("  عرض\u200f   المزيد من الردود "), "عرض المزيد من الردود")

    def test_expand_control_text_matches_english_and_arabic(self) -> None:
        self.assertTrue(is_expand_control_text("View more comments"))
        self.assertTrue(is_expand_control_text("عرض المزيد من الردود"))
        self.assertTrue(is_expand_control_text("عرض التعليقات السابقة"))

    def test_expand_control_text_ignores_login(self) -> None:
        self.assertFalse(is_expand_control_text("تسجيل الدخول"))
        self.assertFalse(is_expand_control_text("Log in"))

    def test_sort_control_text_matches_live_labels(self) -> None:
        self.assertTrue(is_sort_control_text("الأكثر ملاءمة"))
        self.assertTrue(is_sort_control_text("كل التعليقات"))
        self.assertTrue(is_sort_control_text("Most relevant"))

    def test_all_comments_text_matches_arabic_and_english(self) -> None:
        self.assertTrue(is_all_comments_text("كل التعليقات"))
        self.assertTrue(is_all_comments_text("All comments"))
        self.assertFalse(is_all_comments_text("الأكثر ملاءمة"))

    def test_newest_text_matches_arabic_and_english(self) -> None:
        self.assertTrue(is_newest_comments_text("الأحدث"))
        self.assertTrue(is_newest_comments_text("Newest"))
        self.assertFalse(is_newest_comments_text("كل التعليقات"))


if __name__ == "__main__":
    unittest.main()
