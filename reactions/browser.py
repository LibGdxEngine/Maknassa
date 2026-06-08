from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import (
    BrowserContext,
    Error,
    Page,
    TimeoutError,
    sync_playwright,
)
from playwright_stealth import Stealth
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from reactions._js import JS_HELPERS
from reactions.config import ReactionConfig
from reactions.extractor import normalize_url_with_keys, parse_reactor
from reactions.models import RawReactorCandidate, ReactorRecord, SessionStats
from reactions.selectors import (
    ALL_REACTIONS_LABELS,
    REACTION_LABELS,
    REACTION_SUMMARY_LABELS,
    is_login_wall,
    reaction_type_from_label,
    to_int,
)
from reactions.storage import SQLiteStore

logger = logging.getLogger(__name__)

# In-page JS helpers (norm/lc/visible/findDialog/scrollContainer) live in
# reactions/_js.py so the scraper and the block service share one definition.

# Click the post's reaction-summary control to open the "who reacted" dialog.
# A permalink page contains many reaction summaries (the post, its comments, and
# other posts), so Strategy A collects every summary, reads its reaction COUNT
# from the visible text (Facebook renders "NaN" in the aria-label but the real
# number in the text), and clicks the highest-count one -- i.e. the post itself.
# Strategy B falls back to a reaction emoji's nearest clickable ancestor.
OPEN_REACTIONS_SCRIPT = (
    "(args) => {"
    + JS_HELPERS
    + """
  const ar2en = (s) => (s || '').replace(/[\\u0660-\\u0669]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d));
  const toCount = (s) => { const n = parseInt(ar2en(norm(s)).replace(/[^0-9]/g, ''), 10); return Number.isFinite(n) ? n : 0; };
  const summaryPatterns = args.summaryPatterns.map(lc);
  const reactionLabels = args.reactionLabels.map(lc);

  // Strategy A: pick the highest-count reaction summary.
  const summaries = [...document.querySelectorAll('[role="button"]')]
    .filter(visible)
    .filter((el) => {
      const aria = lc(el.getAttribute('aria-label'));
      return aria && summaryPatterns.some((p) => p && aria.includes(p));
    })
    .map((el) => ({ el, count: toCount(el.innerText), top: el.getBoundingClientRect().top }));
  if (summaries.length) {
    summaries.sort((a, b) => (b.count - a.count) || (a.top - b.top));
    const best = summaries[0];
    best.el.scrollIntoView({ block: 'center' });
    best.el.click();
    return 'summary:' + best.count;
  }

  // Strategy B: reaction emoji -> nearest clickable ancestor.
  const emojiHosts = [...document.querySelectorAll('img[alt], [aria-label]')].filter((el) => {
    const a = lc(el.getAttribute('alt') || el.getAttribute('aria-label'));
    return a && reactionLabels.includes(a);
  });
  for (const host of emojiHosts) {
    let cur = host;
    for (let i = 0; i < 6 && cur; i++) {
      if ((cur.getAttribute('role') === 'button' || cur.tagName === 'A' || cur.getAttribute('tabindex') === '0') && visible(cur)) {
        cur.click();
        return 'emoji-ancestor';
      }
      cur = cur.parentElement;
    }
  }
  return null;
}
"""
)

# Enumerate the reaction tabs inside the open dialog.
ENUM_TABS_SCRIPT = (
    "() => {"
    + JS_HELPERS
    + """
  const dialog = findDialog();
  if (!dialog) return [];
  return [...dialog.querySelectorAll('[role="tab"]')].map((t, i) => {
    const alts = [...t.querySelectorAll('img, image, svg, [aria-label]')]
      .map((x) => norm(x.getAttribute('alt') || x.getAttribute('aria-label')))
      .filter(Boolean);
    return {
      index: i,
      text: norm(t.innerText),
      aria: norm(t.getAttribute('aria-label')),
      alts: alts,
    };
  });
}
"""
)

# Click the tab at a given index.
CLICK_TAB_SCRIPT = (
    "(index) => {"
    + JS_HELPERS
    + """
  const dialog = findDialog();
  if (!dialog) return false;
  const tabs = [...dialog.querySelectorAll('[role="tab"]')];
  if (index < 0 || index >= tabs.length) return false;
  tabs[index].click();
  return true;
}
"""
)

# Collect reactor anchors from the dialog's scroll area, then scroll one step.
# Returns the visible {name, profile_url} candidates plus whether we hit bottom.
SCROLL_AND_COLLECT_SCRIPT = (
    "(doScroll) => {"
    + JS_HELPERS
    + """
  const dialog = findDialog();
  if (!dialog) return { rows: [], atBottom: true, found: false };
  const container = scrollContainer(dialog);
  const scope = container || dialog;
  const rows = [];
  const seen = new Set();
  for (const a of scope.querySelectorAll('a[href]')) {
    const name = norm(a.innerText);
    if (!name || name.length > 120) continue;
    const href = a.href;
    if (!href) continue;
    const key = href + '|' + name;
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push({ name, profile_url: href });
  }
  let atBottom = true;
  let scrollHeight = 0;
  if (container) {
    scrollHeight = container.scrollHeight;
    if (doScroll) {
      const before = container.scrollTop;
      // Overlapping step (0.6 of the viewport) so virtualized rows are never
      // scrolled past before they are collected.
      const step = Math.max(container.clientHeight * 0.6, 300);
      container.scrollTop = Math.min(container.scrollHeight, before + step);
      atBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 4;
    }
  }
  return { rows, atBottom, found: true, hasContainer: !!container, scrollHeight };
}
"""
)

# Collect every reactor in the active tab. The dialog list is VIRTUALIZED (rows
# are removed from the DOM once scrolled past), so we accumulate into a Map from
# inside a single in-page loop, recording rows *before* each small overlapping
# scroll step -- this is immune to the cross-call timing gaps that made jump
# scrolling miss batches. Returns the full de-duplicated row set in one call.
COLLECT_TAB_SCRIPT = (
    "async (args) => {"
    + JS_HELPERS
    + """
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const dialog = findDialog();
  if (!dialog) return [];
  const container = scrollContainer(dialog);
  const scope = container || dialog;
  const found = new Map();  // full href -> name (Python normalizes + dedups by profile id)
  const collect = () => {
    for (const a of scope.querySelectorAll('a[href]')) {
      const name = norm(a.innerText);
      if (!name || name.length > 120) continue;
      if (!found.has(a.href)) found.set(a.href, name);
    }
  };
  if (!container) {
    collect();
    return [...found].map(([href, name]) => ({ profile_url: href, name }));
  }
  let lastSize = -1;
  let stable = 0;
  for (let i = 0; i < args.maxRounds; i++) {
    collect();
    const before = container.scrollTop;
    container.scrollTop = Math.min(
      container.scrollHeight, before + Math.max(container.clientHeight * 0.5, 200)
    );
    await sleep(args.sleepMs);
    const atBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 4;
    if (found.size === lastSize && atBottom) {
      stable += 1;
      if (stable >= args.stableNeeded) break;
    } else {
      stable = 0;
    }
    lastSize = found.size;
  }
  collect();
  return [...found].map(([href, name]) => ({ profile_url: href, name }));
}
"""
)


# --------------------------------------------------------------------------- #
# Shared persistent session (used by the scraper and the blocker).
# --------------------------------------------------------------------------- #
@contextmanager
def persistent_page(
    config: ReactionConfig, headless: bool | None = None
) -> Iterator[tuple[BrowserContext, Page]]:
    """Launch a stealthed, persistent-profile Chromium and yield (context, page).

    The persistent ``user_data_dir`` carries your Facebook login across runs --
    log in by hand once and the cookies are reused (same approach as the old
    scraper's ``--profile-dir``). ``headless`` overrides ``config.headless`` (the
    login flow forces a headed window).
    """
    stealth = Stealth()
    is_headless = config.headless if headless is None else headless
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(config.profile_dir),
            headless=is_headless,
            viewport={"width": 1440, "height": 1600},
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            stealth.apply_stealth_sync(page)
            yield context, page
        finally:
            context.close()


def login_flow(config: ReactionConfig, timeout_s: int = 300, poll_s: float = 3.0) -> str | None:
    """Open Facebook headed and wait until you log in.

    Detects a completed login via the ``c_user`` cookie (Facebook sets it to your
    numeric account id once authenticated) so no credentials ever pass through
    this tool. Returns the ``c_user`` id on success, or ``None`` on timeout.
    """
    with persistent_page(config, headless=False) as (context, page):
        page.goto(
            "https://www.facebook.com/",
            wait_until="domcontentloaded",
            timeout=config.navigation_timeout_ms,
        )
        print("A browser window opened. Log in to Facebook there; this waits for you...")
        waited = 0.0
        while waited < timeout_s:
            c_user = next((c["value"] for c in context.cookies() if c["name"] == "c_user"), None)
            if c_user:
                page.wait_for_timeout(1500)
                return c_user
            page.wait_for_timeout(int(poll_s * 1000))
            waited += poll_s
    return None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    retry=retry_if_exception_type((TimeoutError, Error)),
    reraise=True,
)
def navigate(page: Page, url: str, config: ReactionConfig) -> None:
    """Go to ``url`` and fail loudly if Facebook bounces us to a login wall."""
    page.goto(url, wait_until="domcontentloaded", timeout=config.navigation_timeout_ms)
    page.wait_for_timeout(config.settle_timeout_ms)
    current = page.url.lower()
    if "login" in current or "checkpoint" in current:
        raise RuntimeError(
            "Reached a Facebook login/checkpoint page. Run once headed and log in "
            "so the persistent profile stores your session."
        )


class ReactionScraper:
    """Open a post, open the reactions dialog, and collect reactors per type."""

    def __init__(self, config: ReactionConfig, store: SQLiteStore) -> None:
        self.config = config
        self.store = store
        self.stats = SessionStats()

    def run(self) -> tuple[int, SessionStats]:
        session_id = self.store.start_session(
            post_url=self.config.post_url,
            profile_dir=self.config.profile_dir,
            headless=self.config.headless,
        )
        status, notes = "completed", None
        try:
            with persistent_page(self.config) as (_context, page):
                navigate(page, self.config.post_url, self.config)
                self.store.update_session_context(
                    session_id,
                    canonical_post_url=normalize_url_with_keys(page.url, page.url),
                    page_locale=page.locator("html").get_attribute("lang"),
                    logged_out=is_login_wall(page.locator("body").inner_text()),
                )
                self._open_dialog(page, session_id)
                self._scrape_all_tabs(page, session_id)
        except Exception as exc:  # noqa: BLE001 - recorded then re-raised
            status, notes = "failed", str(exc)
            self.stats.failures += 1
            logger.error("scrape run failed for %s: %s", self.config.post_url, exc)
            self.store.record_failure(session_id, "run", self.config.post_url, str(exc))
            raise
        finally:
            self.store.finish_session(session_id, status, self.stats, notes=notes)
        return session_id, self.stats

    def _open_dialog(self, page: Page, session_id: int) -> None:
        strategy = page.evaluate(
            OPEN_REACTIONS_SCRIPT,
            {
                "summaryPatterns": list(REACTION_SUMMARY_LABELS),
                "reactionLabels": [label for labels in REACTION_LABELS.values() for label in labels],
            },
        )
        if not strategy:
            raise RuntimeError(
                "Could not find the reaction-summary control. Run `inspect` mode to "
                "capture the live aria-labels and update reactions/selectors.py."
            )
        try:
            page.wait_for_selector(
                '[role="dialog"] [role="tab"]', timeout=self.config.dialog_timeout_ms
            )
        except TimeoutError:
            # Some posts open a dialog with a single list and no tabs; tolerate it.
            page.wait_for_selector('[role="dialog"]', timeout=self.config.dialog_timeout_ms)
        page.wait_for_timeout(self.config.settle_timeout_ms)

    def _scrape_all_tabs(self, page: Page, session_id: int) -> None:
        tabs = page.evaluate(ENUM_TABS_SCRIPT)
        # Map each tab to a canonical reaction type, carrying Facebook's own count
        # (the tab badge text) so we can report captured-vs-total transparently.
        typed_tabs: list[tuple[int, str, int]] = []
        for tab in tabs:
            blob = " ".join([tab.get("aria", ""), tab.get("text", ""), *tab.get("alts", [])])
            reaction_type = reaction_type_from_label(blob)
            is_all = any(
                self._norm(pattern) in self._norm(blob) for pattern in ALL_REACTIONS_LABELS
            )
            badge = to_int(tab.get("text"))
            if reaction_type:
                typed_tabs.append((tab["index"], reaction_type, badge))
            elif is_all:
                typed_tabs.append((tab["index"], "all", badge))

        # Prefer per-type tabs; only fall back to the "All" tab when there are none.
        per_type = [(i, t, c) for i, t, c in typed_tabs if t != "all"]
        targets = per_type or [(i, t, c) for i, t, c in typed_tabs if t == "all"]
        if not targets:
            # No recognizable tabs -> scrape whatever the dialog currently shows.
            targets = [(-1, "unknown", 0)]

        for index, reaction_type, badge in targets:
            if index >= 0:
                page.evaluate(CLICK_TAB_SCRIPT, index)
                page.wait_for_timeout(self.config.settle_timeout_ms)
            captured = self._scrape_active_tab(page, session_id, reaction_type)
            self.stats.per_type_counts[reaction_type] = captured
            if badge:
                self.stats.per_type_expected[reaction_type] = badge
        self._warn_on_undercount()

    def _warn_on_undercount(self) -> None:
        """Flag tabs where we stored materially fewer reactors than Facebook's own
        badge count -- the signature of a virtualization miss (rows scrolled past
        before they were collected). Small gaps are normal: deleted/unlinkable
        accounts have no profile anchor to store. Reads existing stats only.
        """
        for reaction_type, expected in self.stats.per_type_expected.items():
            captured = self.stats.per_type_counts.get(reaction_type, 0)
            gap = expected - captured
            if expected > 0 and gap > max(2, int(expected * 0.1)):
                logger.warning(
                    "%s: stored %d of %d reacted (%d missing) -- possible "
                    "virtualization miss; consider raising --max-scroll-rounds",
                    reaction_type,
                    captured,
                    expected,
                    gap,
                )

    def _collect_active_tab(self, page: Page, reaction_type: str) -> list[ReactorRecord]:
        """Scrape the active tab into normalized, de-duplicated records.

        Pure data path with no persistence: run the virtualization-safe in-page
        collector, normalize each row via :func:`parse_reactor`, and de-dup by
        ``profile_key``. Kept separate from storage so it is unit-testable with a
        stubbed ``page`` (no live browser, no DB). Exceptions propagate to the
        caller, which records the failure.
        """
        locale = page.locator("html").get_attribute("lang")
        rows = page.evaluate(
            COLLECT_TAB_SCRIPT,
            {
                "maxRounds": self.config.max_scroll_rounds,
                "sleepMs": 350,
                "stableNeeded": self.config.max_idle_rounds,
            },
        )
        records: list[ReactorRecord] = []
        seen_keys: set[str] = set()
        for row in rows:
            self.stats.discovered_rows += 1
            record = parse_reactor(
                RawReactorCandidate(
                    name_hint=row.get("name"),
                    profile_url_hint=row.get("profile_url"),
                    reaction_type=reaction_type,
                    source_url=self.config.post_url,
                    page_locale=locale,
                )
            )
            if record is None or record.profile_key in seen_keys:
                continue
            seen_keys.add(record.profile_key)
            records.append(record)
        return records

    def _scrape_active_tab(self, page: Page, session_id: int, reaction_type: str) -> int:
        """Collect every reactor in the active tab (virtualization-safe) and store."""
        try:
            records = self._collect_active_tab(page, reaction_type)
        except Exception as exc:  # noqa: BLE001
            self.stats.failures += 1
            logger.warning("collect failed for %s tab: %s", reaction_type, exc)
            self.store.record_failure(session_id, "collect", reaction_type, str(exc))
            return 0

        stored = 0
        for record in records:
            if self._store(session_id, record):
                stored += 1
        return stored

    def _store(self, session_id: int, record: ReactorRecord) -> bool:
        try:
            newly = self.store.upsert_reactor(session_id, record)
        except Exception as exc:  # noqa: BLE001
            self.stats.failures += 1
            logger.warning("store failed for %s: %s", record.profile_key, exc)
            self.store.record_failure(session_id, "store", record.profile_key, str(exc))
            return False
        if newly:
            self.stats.stored_reactors += 1
        else:
            self.stats.duplicate_reactors += 1
        return newly

    @staticmethod
    def _norm(value: str) -> str:
        return " ".join((value or "").split()).casefold()


# --------------------------------------------------------------------------- #
# Inspect mode: dump live roles / aria-labels / text so real selector strings
# can be confirmed and pasted into reactions/selectors.py.
# --------------------------------------------------------------------------- #
DUMP_CLICKABLES_SCRIPT = (
    "() => {"
    + JS_HELPERS
    + """
  const out = [];
  for (const el of document.querySelectorAll('[role="button"], [role="link"], [role="tab"], [role="menuitem"], a[href]')) {
    if (!visible(el)) continue;
    const aria = norm(el.getAttribute('aria-label'));
    const text = norm(el.innerText).slice(0, 60);
    if (!aria && !text) continue;
    out.push({ role: el.getAttribute('role') || el.tagName.toLowerCase(), aria, text, href: el.getAttribute('href') || '' });
  }
  return out.slice(0, 400);
}
"""
)


def dump_inspection(config: ReactionConfig, profile_url: str | None = None) -> dict:
    """Open the post (and optionally a profile) and return a DOM signal report."""
    report: dict = {"post_url": config.post_url}
    with persistent_page(config) as (_context, page):
        navigate(page, config.post_url, config)
        report["page_locale"] = page.locator("html").get_attribute("lang")
        report["post_clickables"] = page.evaluate(DUMP_CLICKABLES_SCRIPT)
        strategy = page.evaluate(
            OPEN_REACTIONS_SCRIPT,
            {
                "summaryPatterns": list(REACTION_SUMMARY_LABELS),
                "reactionLabels": [label for labels in REACTION_LABELS.values() for label in labels],
            },
        )
        report["open_strategy"] = strategy
        if strategy:
            try:
                page.wait_for_selector('[role="dialog"]', timeout=config.dialog_timeout_ms)
                page.wait_for_timeout(config.settle_timeout_ms)
                report["dialog_tabs"] = page.evaluate(ENUM_TABS_SCRIPT)
                sample = page.evaluate(SCROLL_AND_COLLECT_SCRIPT, False)
                report["dialog_sample_rows"] = sample.get("rows", [])[:10]
            except TimeoutError:
                report["dialog_tabs"] = []
        if profile_url:
            navigate(page, profile_url, config)
            report["profile_clickables"] = page.evaluate(DUMP_CLICKABLES_SCRIPT)
    return report


def write_inspection(report: dict, out_path: Path | None) -> None:
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
    print(payload)
