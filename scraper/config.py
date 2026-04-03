from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ScrapeConfig:
    post_url: str
    db_path: Path
    profile_dir: Path
    headless: bool
    skip_sort_switch: bool
    max_idle_rounds: int
    max_expand_rounds: int
    debug_dir: Path | None = None
    save_html_snapshots: bool = False
    save_screenshot: bool = False
    navigation_timeout_ms: int = 45_000
    settle_timeout_ms: int = 1_200
