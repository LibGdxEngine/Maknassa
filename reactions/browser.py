from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import (
    BrowserContext,
    Error,
    Page,
    TimeoutError,
    sync_playwright,
)
from playwright_stealth import Stealth
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from reactions._js import JS_COLLECT_LOOP, JS_HELPERS, JS_SLEEP
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
# other posts), so Strategy A collects every summary, reads its reaction COUNT, and
# clicks the highest-count one -- i.e. the post itself. Facebook labels these two
# different ways, and the count lives in a DIFFERENT place for each:
#   * "see who reacted" phrase controls (comments/secondary): aria-label is
#     "...who reacted"/"...من التفاعلات" with "NaN" for the number, and the real
#     count is in the visible TEXT.
#   * reaction-emoji summaries (the post's engagement bar): aria-label is
#     "<reaction>: <N> people" (e.g. "أعجبني: 306 أشخاص") -- the count is in the
#     ARIA-LABEL and the text is empty.
# We must read the count from the right place for each, and crucially NOT confuse a
# reaction-emoji summary with the like/react TOGGLE button (aria "Remove Like" /
# "إزالة أعجبني"), whose visible text shows the post's total: the toggle has no
# number IN its aria, so requiring a count in the aria for reaction-name controls
# excludes it. Strategy B falls back to a reaction emoji's nearest clickable ancestor.
OPEN_REACTIONS_SCRIPT = (
    "(args) => {"
    + JS_HELPERS
    + """
  const ar2en = (s) => (s || '').replace(/[\\u0660-\\u0669]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d));
  const toCount = (s) => { const n = parseInt(ar2en(norm(s)).replace(/[^0-9]/g, ''), 10); return Number.isFinite(n) ? n : 0; };
  const summaryPatterns = args.summaryPatterns.map(lc);
  const reactionLabels = args.reactionLabels.map(lc);

  // Strategy A: click the highest-count reaction summary on the page (the post's
  // own summary outranks any comment's). For a summary-phrase control the count is
  // in the text; for a reaction-emoji summary it is in the aria-label. A
  // reaction-name control with NO number in its aria is the like/react toggle, so
  // it is skipped (ok stays false).
  const summaries = [...document.querySelectorAll('[role="button"]')]
    .filter(visible)
    .map((el) => {
      const ariaRaw = el.getAttribute('aria-label') || '';
      const aria = lc(ariaRaw);
      let count = 0, ok = false;
      if (aria && summaryPatterns.some((p) => p && aria.includes(p))) {
        count = toCount(el.innerText); ok = true;
      } else if (aria && reactionLabels.some((p) => p && aria.includes(p))) {
        const ariaCount = toCount(ariaRaw);
        if (ariaCount > 0) { count = ariaCount; ok = true; }
      }
      return { el, count, ok, top: el.getBoundingClientRect().top };
    })
    .filter((c) => c.ok);
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

# True once the reactions dialog has actually rendered content. Uses findDialog (so
# it ignores other dialogs a permalink shows -- notifications, etc., several of
# which are hidden) and accepts either per-type tabs or at least one reactor-name
# anchor, which also covers a single "All" list dialog that has no tabs.
DIALOG_READY_SCRIPT = (
    "() => {"
    + JS_HELPERS
    + """
  const d = findDialog();
  if (!d) return false;
  if (d.querySelector('[role="tab"]')) return true;
  for (const a of d.querySelectorAll('a[href]')) {
    if (norm(a.innerText)) return true;
  }
  return false;
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
  tabs[index].scrollIntoView({ block: 'nearest', inline: 'center' });
  tabs[index].click();
  return true;
}
"""
)

# Whether the tab at ``index`` is the active (aria-selected) one. Facebook collapses
# the lower-count reaction tabs under a "More" overflow: their [role="tab"] exists in
# the DOM but a direct click does not switch the list, so we detect that here and
# fall back to the overflow menu.
TAB_SELECTED_SCRIPT = (
    "(index) => {"
    + JS_HELPERS
    + """
  const dialog = findDialog();
  if (!dialog) return false;
  const tabs = [...dialog.querySelectorAll('[role="tab"]')];
  return index >= 0 && index < tabs.length && tabs[index].getAttribute('aria-selected') === 'true';
}
"""
)

# Open the "More" (المزيد) reaction-tab overflow menu, if present.
OPEN_MORE_MENU_SCRIPT = (
    "(moreLabels) => {"
    + JS_HELPERS
    + """
  const dialog = findDialog();
  if (!dialog) return false;
  const labels = moreLabels.map(lc);
  const more = [...dialog.querySelectorAll('[role="tab"]')].find((t) => {
    const blob = lc(t.innerText) + ' ' + lc(t.getAttribute('aria-label'));
    return labels.some((l) => l && blob.includes(l));
  });
  if (!more) return false;
  more.scrollIntoView({ block: 'nearest', inline: 'center' });
  more.click();
  return true;
}
"""
)

# Click the overflow-menu item (role=menuitemradio) whose aria-label names one of the
# given reaction labels -- the way to select a tab that lives under "More".
CLICK_OVERFLOW_ITEM_SCRIPT = (
    "(labels) => {"
    + JS_HELPERS
    + """
  const wanted = labels.map(lc);
  const items = [...document.querySelectorAll('[role="menuitemradio"], [role="menuitem"]')].filter(visible);
  const hit = items.find((it) => {
    const aria = lc(it.getAttribute('aria-label'));
    return aria && wanted.some((l) => l && aria.includes(l));
  });
  if (!hit) return false;
  hit.click();
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
  // Mirror the live engine's container choice (reactor-anchor ancestry first),
  // and surface how many candidates exist so inspect mode can confirm selection.
  const candidates = scrollCandidates(dialog);
  const container = candidates[0] || null;
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
  return { rows, atBottom, found: true, hasContainer: !!container, candidateCount: candidates.length, scrollHeight };
}
"""
)

# Collect every reactor in the active tab. The dialog list is VIRTUALIZED (rows
# are removed from the DOM once scrolled past), so the shared JS_COLLECT_LOOP
# accumulates into a Map while scrolling the list to the bottom. The per-row
# extractor here yields {profile_url, name}; Python normalizes + dedups by profile
# id downstream (avatars are ignored on this CLI path).
COLLECT_TAB_SCRIPT = (
    "async (args) => {"
    + JS_HELPERS
    + JS_SLEEP
    + JS_COLLECT_LOOP.replace("__EXTRACT__", "{ profile_url: a.href, name: name }")
    + "}"
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


def _norm_plain(value: str) -> str:
    """Whitespace-collapse + casefold (matches the old ``ReactionScraper._norm``)."""
    return " ".join((value or "").split()).casefold()


def _tab_to_typed(tab: dict) -> tuple[int, str, int] | None:
    """Pure: map one enumerated tab to ``(index, reaction_type|'all', badge)``, or None."""
    blob = " ".join([tab.get("aria", ""), tab.get("text", ""), *tab.get("alts", [])])
    badge = to_int(tab.get("text"))
    reaction_type = reaction_type_from_label(blob)
    if reaction_type:
        return (tab["index"], reaction_type, badge)
    norm_blob = _norm_plain(blob)
    if any(_norm_plain(pattern) in norm_blob for pattern in ALL_REACTIONS_LABELS):
        return (tab["index"], "all", badge)
    return None


def select_targets(tabs: list[dict]) -> list[tuple[int, str, int]]:
    """Pure: choose which tabs to scrape -- per-type tabs preferred, else the
    'All' tab, else a single 'unknown' fallback. No I/O; unit-testable."""
    typed = [t for t in map(_tab_to_typed, tabs) if t is not None]
    per_type = [t for t in typed if t[1] != "all"]
    targets = per_type or [t for t in typed if t[1] == "all"]
    return targets or [(-1, "unknown", 0)]


def collect_records(
    post_url: str, reaction_type: str, locale: str | None, rows: list[dict]
) -> list[ReactorRecord]:
    """Pure transform: raw DOM rows -> normalized, de-duplicated reactor records.

    No I/O and no shared state, so it is fully unit-testable without a browser.
    Each row becomes a candidate, is parsed (dropping non-profile rows), and the
    first record for any ``profile_key`` wins (later duplicates are skipped).
    """
    records: list[ReactorRecord] = []
    seen: set[str] = set()
    for row in rows:
        candidate = RawReactorCandidate(
            name_hint=row.get("name"),
            profile_url_hint=row.get("profile_url"),
            reaction_type=reaction_type,
            source_url=post_url,
            page_locale=locale,
        )
        record = parse_reactor(candidate)
        if record is None or record.profile_key in seen:
            continue
        seen.add(record.profile_key)
        records.append(record)
    return records


def open_reactions_dialog(page: Page, config: ReactionConfig) -> int:
    """Click the post's reaction summary and wait for the "who reacted" dialog.

    Shared by :class:`ReactionScraper` and the Streamlit UI fetch
    (:mod:`reactions.ui_fetch`) so both open the dialog identically. Raises if the
    reaction-summary control can't be found (run ``inspect`` mode to refresh
    selectors); tolerates a dialog that renders a single list with no tabs.

    Returns the reaction count Facebook showed on the clicked summary (``'summary:510'``
    -> ``510``), or ``0`` if none was parseable. Callers use it as a completeness
    target when the dialog has no per-type tabs to sum badges from.
    """
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
    # Wait for the reactions dialog itself to render -- via findDialog, so other
    # dialogs on the page (e.g. a hidden "Notifications" dialog that a raw
    # '[role="dialog"]' selector would match first) don't cause a false timeout.
    # Tolerates a single-list dialog with no tabs.
    try:
        page.wait_for_function(DIALOG_READY_SCRIPT, timeout=config.dialog_timeout_ms)
    except TimeoutError:
        pass  # proceed; the collect loop no-ops if the dialog is genuinely empty
    page.wait_for_timeout(config.settle_timeout_ms)
    match = re.search(r"(\d+)\s*$", strategy)
    return int(match.group(1)) if match else 0


# Labels for the "More" reaction-tab overflow control (Facebook collapses the
# lower-count reaction tabs behind it).
MORE_TAB_LABELS: tuple[str, ...] = ("More", "Show more", "المزيد", "عرض المزيد")


def select_reaction_tab(
    page: Page, config: ReactionConfig, index: int, reaction_type: str
) -> bool:
    """Activate the reaction tab at ``index`` and return True once it is selected.

    Facebook shows only the top few reaction tabs and hides the rest under a "More"
    (المزيد) overflow whose ``[role="tab"]`` is in the DOM but does NOT switch the
    list on a direct click. So we click the tab and, if it did not become selected,
    open "More" and click the overflow menu item (``role="menuitemradio"``) whose
    aria-label names this ``reaction_type``. ``index < 0`` (a tab-less single-list
    dialog) is a no-op success. Shared by the CLI scraper and the Streamlit fetch so
    both walk the tabs identically.
    """
    if index < 0:
        return True
    # Try the "More" overflow menu FIRST. It holds the lower-count reaction tabs, and
    # directly clicking an overflow tab poisons the "More" button so it won't open
    # afterwards -- so we never click an overflow tab. If this reaction isn't in the
    # overflow (i.e. it's a directly-visible tab), dismiss the menu and click the tab.
    labels = list(REACTION_LABELS.get(reaction_type, ()))
    if labels and page.evaluate(OPEN_MORE_MENU_SCRIPT, list(MORE_TAB_LABELS)):
        page.wait_for_timeout(config.settle_timeout_ms)
        if page.evaluate(CLICK_OVERFLOW_ITEM_SCRIPT, labels):
            page.wait_for_timeout(config.settle_timeout_ms)
            return True
        page.keyboard.press("Escape")  # not an overflow reaction; close the menu
        page.wait_for_timeout(config.settle_timeout_ms)
    page.evaluate(CLICK_TAB_SCRIPT, index)
    page.wait_for_timeout(config.settle_timeout_ms)
    return bool(page.evaluate(TAB_SELECTED_SCRIPT, index))


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
                    canonical_post_url=normalize_url_with_keys((), page.url, page.url),
                    page_locale=page.locator("html").get_attribute("lang"),
                    logged_out=is_login_wall(page.locator("body").inner_text()),
                )
                summary_count = self._open_dialog(page, session_id)
                self._scrape_all_tabs(page, session_id, summary_count)
        except Exception as exc:  # noqa: BLE001 - recorded then re-raised
            status, notes = "failed", str(exc)
            self.stats.failures += 1
            logger.error("scrape run failed for %s: %s", self.config.post_url, exc)
            self.store.record_failure(session_id, "run", self.config.post_url, str(exc))
            raise
        finally:
            self.store.finish_session(session_id, status, self.stats, notes=notes)
        return session_id, self.stats

    def _open_dialog(self, page: Page, session_id: int) -> int:
        return open_reactions_dialog(page, self.config)

    def _scrape_all_tabs(self, page: Page, session_id: int, summary_count: int = 0) -> None:
        # Pure target selection (which tabs, in what order, with Facebook's own
        # badge count) is factored into select_targets; here we only drive effects.
        targets = select_targets(page.evaluate(ENUM_TABS_SCRIPT))
        for index, reaction_type, badge in targets:
            if not select_reaction_tab(page, self.config, index, reaction_type):
                logger.warning("could not activate %s tab (index %d); skipping", reaction_type, index)
                continue
            # The scroll loop stops once it has gathered this many reactors: the
            # tab's own badge, or (for a tab-less "All" dialog) the summary count.
            target = badge or summary_count
            captured = self._scrape_active_tab(page, session_id, reaction_type, target)
            self.stats.per_type_counts[reaction_type] = captured
            if badge:
                self.stats.per_type_expected[reaction_type] = badge
        # A tab-less dialog (single "All" list) has no per-type badge to compare
        # against; fall back to the count Facebook showed on the summary we clicked
        # so the undercount check still fires.
        if summary_count and not self.stats.per_type_expected and len(targets) == 1:
            self.stats.per_type_expected[targets[0][1]] = summary_count
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

    def _collect_active_tab(
        self, page: Page, reaction_type: str, target: int = 0
    ) -> list[ReactorRecord]:
        """Run the virtualization-safe in-page collector (the effects), then hand
        the raw rows to the pure :func:`collect_records` pipeline for normalization
        and de-duplication. ``target`` is the reactor count to scroll until (the
        tab's badge). Exceptions propagate to the caller, which records them.
        """
        locale = page.locator("html").get_attribute("lang")
        rows = page.evaluate(
            COLLECT_TAB_SCRIPT,
            {
                "target": target,
                "maxRounds": self.config.max_scroll_rounds,
                "sleepMs": 700,  # dwell long enough for a lazy-loaded batch to render
                "stableNeeded": self.config.max_idle_rounds,
            },
        )
        self.stats.discovered_rows += len(rows)
        return collect_records(self.config.post_url, reaction_type, locale, rows)

    def _scrape_active_tab(
        self, page: Page, session_id: int, reaction_type: str, target: int = 0
    ) -> int:
        """Collect every reactor in the active tab (virtualization-safe) and store."""
        try:
            records = self._collect_active_tab(page, reaction_type, target)
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
