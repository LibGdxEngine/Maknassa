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
    # Which reaction tabs to scrape (canonical REACTION_LABELS keys). None = all.
    # Best-effort: ignored when the dialog exposes no per-type tabs.
    reaction_types: tuple[str, ...] | None = None
    # Timeouts.
    navigation_timeout_ms: int = 45_000
    settle_timeout_ms: int = 1_200
    dialog_timeout_ms: int = 12_000
    # How long to wait for the profile action bar ("..." menu) to hydrate after a
    # navigation. Replaces the old `networkidle` wait, which never settled on
    # Facebook's streaming SPA and burned its full timeout every load.
    action_ready_timeout_ms: int = 8_000
    # Blocking safety knobs.
    dry_run: bool = True
    block_min_delay_s: float = 2.0
    block_max_delay_s: float = 6.0
    # Max successful blocks before stopping. 0 (or negative) means unlimited -- the
    # default. Honored by every path: the DB-driven blocker (as a per-day cap via
    # count_blocked_today) and the by-URL/Streamlit batch (as a per-run cap).
    daily_cap: int = 0
    confirm_each: bool = True
    # When True, verify a block/unblock by reloading the profile (thorough but
    # doubles page loads). Default False: confirm from the dialog closing instead.
    verify_reload: bool = False
    # Debug artifacts.
    debug_dir: Path | None = None
    save_html_snapshots: bool = False
    save_screenshot: bool = False
