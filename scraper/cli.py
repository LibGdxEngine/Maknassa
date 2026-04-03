from __future__ import annotations

import argparse
from pathlib import Path

from scraper.browser import FacebookCommentScraper
from scraper.config import ScrapeConfig
from scraper.storage import SQLiteStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape Facebook comments for a single post URL.")
    parser.add_argument("post_url", help="Facebook post URL to scrape")
    parser.add_argument("--db-path", default="comments.db", help="SQLite database path")
    parser.add_argument(
        "--profile-dir",
        default=".profiles/facebook",
        help="Persistent Playwright profile directory used for authorized viewing",
    )
    parser.add_argument("--headless", action="store_true", help="Run the browser in headless mode")
    parser.add_argument("--skip-sort-switch", action="store_true", help="Skip switching comment sort to All comments")
    parser.add_argument("--max-idle-rounds", type=int, default=3, help="Stop after this many rounds with no new nodes")
    parser.add_argument("--max-expand-rounds", type=int, default=50, help="Hard cap on expand/scroll rounds")
    parser.add_argument("--debug-dir", default=None, help="Optional directory for HTML/screenshots/debug metadata")
    parser.add_argument("--save-html-snapshots", action="store_true", help="Save page HTML snapshots into the debug directory")
    parser.add_argument("--save-screenshot", action="store_true", help="Save a screenshot into the debug directory")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    config = ScrapeConfig(
        post_url=args.post_url,
        db_path=Path(args.db_path).expanduser().resolve(),
        profile_dir=Path(args.profile_dir).expanduser().resolve(),
        headless=bool(args.headless),
        skip_sort_switch=bool(args.skip_sort_switch),
        max_idle_rounds=max(args.max_idle_rounds, 1),
        max_expand_rounds=max(args.max_expand_rounds, 1),
        debug_dir=Path(args.debug_dir).expanduser().resolve() if args.debug_dir else None,
        save_html_snapshots=bool(args.save_html_snapshots),
        save_screenshot=bool(args.save_screenshot),
    )
    store = SQLiteStore(config.db_path)
    scraper = FacebookCommentScraper(config, store)
    session_id, stats = scraper.run()
    print(
        f"session_id={session_id} stored_comments={stats.stored_comments} "
        f"discovered_nodes={stats.discovered_nodes} duplicate_comments={stats.duplicate_comments} "
        f"failures={stats.failures}"
    )
    return 0
