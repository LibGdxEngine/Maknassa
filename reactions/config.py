from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ReactionConfig:
    """Runtime configuration shared by the scrape, block and inspect flows."""

    post_url: str
    db_path: Path
    profile_dir: Path
    headless: bool = False
    # Scroll loop (mirrors the old scraper's expand loop).
    max_idle_rounds: int = 3
    max_scroll_rounds: int = 200
    # Timeouts.
    navigation_timeout_ms: int = 45_000
    settle_timeout_ms: int = 1_200
    dialog_timeout_ms: int = 12_000
    # Blocking safety knobs.
    dry_run: bool = True
    block_min_delay_s: float = 8.0
    block_max_delay_s: float = 25.0
    daily_cap: int = 50
    confirm_each: bool = True
    # Debug artifacts.
    debug_dir: Path | None = None
    save_html_snapshots: bool = False
    save_screenshot: bool = False
