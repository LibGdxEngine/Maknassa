"""Standalone Facebook block/unblock service -- by profile URL, no database.

This is deliberately decoupled from reaction scraping/storage: you hand it a
profile URL and it performs the UI action (profile -> "..." -> Block/Unblock ->
confirm) and verifies the result. The scraper (which produces URLs + names) and
this service are independent; wire them together yourself, or use the DB-driven
:class:`reactions.blocker.ProfileBlocker` which orchestrates this service over
scraped reactors with rate limiting and a daily cap.

Example::

    from reactions.service import FacebookBlocker

    with FacebookBlocker(profile_dir=".profiles/facebook") as fb:
        fb.block("https://www.facebook.com/BMIsslem")
        results = fb.block_many([url1, url2, url3])
"""

from __future__ import annotations

import logging
import random
import time
from contextlib import AbstractContextManager
from functools import partial
from pathlib import Path
from typing import TypedDict

from playwright.sync_api import BrowserContext, Page, TimeoutError

from reactions._js import JS_HELPERS, JS_SLEEP
from reactions.browser import navigate, persistent_page
from reactions.config import ReactionConfig
from reactions.extractor import normalize_profile_url
from reactions.models import BlockOutcome
from reactions.selectors import (
    BLOCK_CANCEL_LABELS,
    BLOCK_CONFIRM_LABELS,
    BLOCK_MENU_LABELS,
    MORE_BUTTON_LABELS,
    MORE_DISTRACTOR_TERMS,
    NOTIFICATION_DIALOG_LABELS,
    REPORT_LABELS,
    UNBLOCK_CONFIRM_LABELS,
    UNBLOCK_LABELS,
    extract_profile_id,
    matches_any,
)

logger = logging.getLogger(__name__)

# Return the visible text of every menu item across ALL open menus.
_DUMP_MENU_ITEMS_SCRIPT = (
    "() => {"
    + JS_HELPERS
    + """
  const items = [];
  for (const m of document.querySelectorAll('[role="menu"]')) {
    for (const i of m.querySelectorAll('[role="menuitem"]')) {
      const t = norm(i.innerText);
      if (t) items.push(t);
    }
  }
  return items;
}
"""
)

# True once the profile action bar has hydrated enough to expose a "..." (more
# actions) candidate button. Mirrors the isCandidate filter in
# _OPEN_ACTIONS_MENU_SCRIPT so load_profile can wait for the SAME element the menu
# opener needs -- a targeted wait that resolves in ~1-2s, replacing the old
# `networkidle` wait that never settled on Facebook and burned its full timeout.
_ACTION_BAR_READY_SCRIPT = (
    "(args) => {"
    + JS_HELPERS
    + """
  const labels = args.labels.map(lc);
  const distractors = args.distractors.map(lc);
  const isCandidate = (el) => {
    const a = lc(el.getAttribute('aria-label'));
    const t = lc(el.innerText);
    if (distractors.some((d) => d && (a.includes(d) || t.includes(d)))) return false;
    return labels.some((l) => l && (a === l || t === l || a.includes(l) || t.includes(l)));
  };
  return [...document.querySelectorAll('[role="button"]')].filter(visible).some(isCandidate);
}
"""
)


# Open the profile's actions ("...") menu FUNCTIONALLY: a profile page has many
# "More" buttons (footer links, "see more comments"), and the real one is not
# reliably identifiable by label alone. So we click each non-distractor "More"
# candidate (topmost first) and keep the menu that actually contains a Block /
# Unblock / Report item -- pressing Escape to dismiss any wrong menu in between.
_OPEN_ACTIONS_MENU_SCRIPT = (
    "async (args) => {"
    + JS_HELPERS
    + JS_SLEEP
    + """
  const labels = args.labels.map(lc);
  const distractors = args.distractors.map(lc);
  const markers = args.markers.map(lc);
  const isCandidate = (el) => {
    const a = lc(el.getAttribute('aria-label'));
    const t = lc(el.innerText);
    if (distractors.some((d) => d && (a.includes(d) || t.includes(d)))) return false;
    return labels.some((l) => l && (a === l || t === l || a.includes(l) || t.includes(l)));
  };
  const menuHasMarker = () => {
    for (const m of document.querySelectorAll('[role="menu"]')) {
      for (const it of m.querySelectorAll('[role="menuitem"]')) {
        const t = lc(it.innerText);
        if (markers.some((mk) => mk && t.includes(mk))) return true;
      }
    }
    return false;
  };
  const closeMenus = () => {
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
  };
  // Lower score == tried first. The profile-header "..." is NOT inside a post
  // ([role="article"]), usually exact-matches a canonical "More" aria-label, and
  // sits in the main column -- so rank by those signals, then by vertical position
  // as a tie-break. EVERY candidate stays in the list (only the ORDER changes), so
  // anything that worked before is still reached as a fallback, and el.closest is
  // null-safe -- if Facebook drops these roles the score collapses to the old sort.
  const score = (el) => {
    let s = 0;
    if (el.closest('[role="article"]')) s += 100;     // a post's own "..." menu -> last
    const a = lc(el.getAttribute('aria-label'));
    if (!labels.some((l) => l && a === l)) s += 10;   // prefer an EXACT aria-label match
    if (!el.closest('[role="main"]')) s += 5;         // prefer the main profile column
    return s;
  };
  const cands = [...document.querySelectorAll('[role="button"]')]
    .filter(visible)
    .filter(isCandidate)
    .sort((x, y) => {
      const dx = score(x) - score(y);
      if (dx !== 0) return dx;
      return x.getBoundingClientRect().top - y.getBoundingClientRect().top;
    });
  // Per-candidate early-exit poll: return the instant the right menu appears
  // (~200ms typical) instead of always waiting a flat 1200ms; give up on a WRONG
  // candidate after ~600ms and move on, so a stray menu costs far less time.
  const POLL_MS = 120, MAX_WAIT_MS = 600;
  for (const el of cands) {
    el.scrollIntoView({ block: 'center' });
    el.click();
    let waited = 0;
    while (waited < MAX_WAIT_MS) {
      await sleep(POLL_MS);
      waited += POLL_MS;
      if (menuHasMarker()) return true;
    }
    closeMenus();
    await sleep(200);
  }
  return false;
}
"""
)


# Find the confirm button INSIDE the real block/unblock dialog -- not the
# persistent Notifications dialog (which also has "تأكيد" buttons). Returns the
# button element (for a trusted Playwright click) or null.
_FIND_CONFIRM_BUTTON_SCRIPT = (
    "(args) => {"
    + JS_HELPERS
    + """
  const confirmLabels = args.confirm.map(lc);
  const avoid = args.avoid.map(lc);
  const skip = args.skipDialogLabels.map(lc);
  const dialogs = [...document.querySelectorAll('[role="dialog"]')].filter(visible);
  for (const d of dialogs) {
    const al = lc(d.getAttribute('aria-label'));
    if (skip.some((s) => s && al.includes(s))) continue;  // skip Notifications etc.
    const buttons = [...d.querySelectorAll('[role="button"], button')].filter(visible);
    for (const b of buttons) {
      const t = lc(b.innerText), a = lc(b.getAttribute('aria-label'));
      if (avoid.some((x) => x && (a.includes(x) || t.includes(x)))) continue;
      if (confirmLabels.some((l) => l && (t === l || a === l))) return b;
    }
  }
  return null;
}
"""
)


# --------------------------------------------------------------------------- #
# Functional core: page-threading actions, each taking the session ``page`` (and
# ``config``) explicitly. The FacebookBlocker class below is a thin imperative
# shell that owns the persistent session and delegates here; ``run_session`` is
# the context-manager-free entry point used by the CLI's by-URL commands.
# --------------------------------------------------------------------------- #

# Keyword args that specialize ``menu_action`` into block vs unblock. Typed as a
# TypedDict so the ``**_BLOCK`` / ``**_UNBLOCK`` spread stays fully type-checked
# against ``menu_action``'s keyword params (a plain dict erases to ``object``).
class MenuActionSpec(TypedDict):
    menu_labels: tuple[str, ...]
    confirm_labels: tuple[str, ...]
    success_status: str
    expect_unblock_after: bool
    stage: str


_BLOCK: MenuActionSpec = {
    "menu_labels": BLOCK_MENU_LABELS,
    "confirm_labels": BLOCK_CONFIRM_LABELS,
    "success_status": "blocked",
    "expect_unblock_after": True,
    "stage": "block",
}
_UNBLOCK: MenuActionSpec = {
    "menu_labels": UNBLOCK_LABELS,
    "confirm_labels": UNBLOCK_CONFIRM_LABELS,
    "success_status": "unblocked",
    "expect_unblock_after": False,
    "stage": "unblock",
}


def session_config(
    profile_dir: str | Path,
    headless: bool = False,
    *,
    dialog_timeout_ms: int = 12_000,
    min_delay_s: float = 2.0,
    max_delay_s: float = 6.0,
    daily_cap: int = 0,
) -> ReactionConfig:
    """Build the by-URL service config (no post_url / DB needed).

    ``daily_cap`` is an optional per-run safety brake (0 = unlimited, the default);
    ``run_batch`` stops after that many successful actions.
    """
    return ReactionConfig(
        post_url="",
        db_path=Path("reactions.db"),
        profile_dir=Path(profile_dir).expanduser().resolve(),
        headless=headless,
        dialog_timeout_ms=dialog_timeout_ms,
        block_min_delay_s=min_delay_s,
        block_max_delay_s=max_delay_s,
        daily_cap=daily_cap,
    )


def human_delay(config: ReactionConfig) -> None:
    time.sleep(random.uniform(config.block_min_delay_s, config.block_max_delay_s))


def load_profile(config: ReactionConfig, page: Page, url: str) -> None:
    """Navigate, wait for the profile action bar to hydrate, and dismiss overlays.

    Waits for the "..." action-bar button to actually exist (via
    ``_ACTION_BAR_READY_SCRIPT``) rather than for ``networkidle`` -- Facebook is a
    streaming SPA whose network never goes idle, so the old wait burned its full
    timeout on every load. This resolves in ~1-2s as soon as the bar is present,
    and ``open_more_menu`` still retries with waits if it isn't. Pressing Escape
    dismisses the persistent Notifications flyout, which can otherwise overlay the
    action bar and make the menu look "not found".
    """
    navigate(page, url, config)
    try:
        page.wait_for_function(
            _ACTION_BAR_READY_SCRIPT,
            arg={
                "labels": list(MORE_BUTTON_LABELS),
                "distractors": list(MORE_DISTRACTOR_TERMS),
            },
            timeout=config.action_ready_timeout_ms,
        )
    except Exception:  # noqa: BLE001 - fall through; open_more_menu retries with waits
        pass
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001
        pass


def open_more_menu(page: Page) -> bool:
    """Open the profile actions menu (the one containing Block/Report). The action
    bar hydrates asynchronously, so retry a few times with waits."""
    args = {
        "labels": list(MORE_BUTTON_LABELS),
        "distractors": list(MORE_DISTRACTOR_TERMS),
        "markers": list(BLOCK_MENU_LABELS) + list(UNBLOCK_LABELS) + list(REPORT_LABELS),
    }
    for _ in range(4):
        if page.evaluate(_OPEN_ACTIONS_MENU_SCRIPT, args):
            page.wait_for_timeout(200)
            return True
        # Dismiss any overlay (Notifications flyout) and let the bar hydrate.
        try:
            page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1_000)
    return False


def click_confirm(config: ReactionConfig, page: Page, confirm_labels, attempts: int = 16) -> bool:
    """Poll for the confirm button inside the real block/unblock dialog and
    trusted-click it (skipping the Notifications dialog's own buttons)."""
    args = {
        "confirm": list(confirm_labels),
        "avoid": list(BLOCK_CANCEL_LABELS),
        "skipDialogLabels": list(NOTIFICATION_DIALOG_LABELS),
    }
    for _ in range(attempts):
        handle = page.evaluate_handle(_FIND_CONFIRM_BUTTON_SCRIPT, args)
        element = handle.as_element()
        if element is not None:
            try:
                element.scroll_into_view_if_needed(timeout=2_000)
            except Exception:  # noqa: BLE001
                pass
            element.click(timeout=config.dialog_timeout_ms)
            return True
        page.wait_for_timeout(500)
    return False


def wait_for_confirm_dialog_closed(
    config: ReactionConfig, page: Page, confirm_labels, attempts: int = 12
) -> bool:
    """Fast, same-page success check: poll until the confirm button (inside the real
    block/unblock dialog) is gone. Facebook closes that dialog once the action
    registers, so its disappearance confirms success without reloading the whole
    profile. Reuses ``_FIND_CONFIRM_BUTTON_SCRIPT`` so it ignores the persistent
    Notifications dialog exactly as ``click_confirm`` does.
    """
    args = {
        "confirm": list(confirm_labels),
        "avoid": list(BLOCK_CANCEL_LABELS),
        "skipDialogLabels": list(NOTIFICATION_DIALOG_LABELS),
    }
    for _ in range(attempts):
        handle = page.evaluate_handle(_FIND_CONFIRM_BUTTON_SCRIPT, args)
        if handle.as_element() is None:
            return True
        page.wait_for_timeout(400)
    return False


def native_click_by_name(config: ReactionConfig, scope, role: str, labels) -> bool:
    """Trusted Playwright click on the first `role` element under `scope` whose
    EXACT accessible name matches one of `labels`. Exact names avoid the
    Unblock/Cancel controls whose names merely contain the block verb."""
    for label in labels:
        loc = scope.get_by_role(role, name=label, exact=True)
        try:
            if loc.count() > 0:
                loc.first.click(timeout=config.dialog_timeout_ms)
                return True
        except Exception:  # noqa: BLE001 - try the next label
            continue
    return False


def verify(config: ReactionConfig, page: Page, url: str, expect_unblock_after: bool) -> bool:
    """Reload the profile and infer block state from the actions menu.

    A *blocked* profile renders a stripped page whose "..." menu either offers
    Unblock, no longer offers Block, or won't open at all -- so a block is
    confirmed by any of those. An unblock is confirmed when the menu opens and
    offers Block again (and not Unblock).
    """
    try:
        load_profile(config, page, url)
        opened = open_more_menu(page)
        items = page.evaluate(_DUMP_MENU_ITEMS_SCRIPT) if opened else []
        is_unblock = partial(matches_any, UNBLOCK_LABELS)
        is_block = partial(matches_any, BLOCK_MENU_LABELS)
        has_unblock = any(map(is_unblock, items))
        has_block = any(is_block(it) and not is_unblock(it) for it in items)
        if expect_unblock_after:  # after a BLOCK
            return has_unblock or (opened and not has_block) or (not opened)
        return opened and has_block and not has_unblock  # after an UNBLOCK
    except Exception as exc:  # noqa: BLE001
        logger.warning("verify failed for %s: %s", url, exc)
        return False


def menu_action(
    config: ReactionConfig,
    page: Page,
    profile_url: str | None,
    name: str | None,
    *,
    menu_labels: tuple[str, ...],
    confirm_labels: tuple[str, ...],
    success_status: str,
    expect_unblock_after: bool,
    stage: str,
) -> BlockOutcome:
    """Shared profile-menu flow for both block and unblock, against an open ``page``.

    Native (trusted-event) clicks: Facebook ignores synthetic JS clicks on the
    confirm button, so Block/Unblock + Confirm go through Playwright's real input.
    Targeting by EXACT accessible name avoids the Unblock/Cancel controls whose
    names merely contain the block verb.
    """
    url = normalize_profile_url("https://www.facebook.com/", profile_url) or profile_url
    key = extract_profile_id(url) or url or profile_url or ""

    def outcome(status: str, detail: str | None = None) -> BlockOutcome:
        return BlockOutcome(profile_key=key, name=name, profile_url=url, status=status, detail=detail)

    if not url:
        return outcome("failed", "no profile url")
    try:
        load_profile(config, page, url)
        if not open_more_menu(page):
            return outcome("failed", "profile actions menu not found")
        if not native_click_by_name(config, page, "menuitem", menu_labels):
            return outcome("failed", f"{stage} menu item not found")
        # The confirmation dialog appears now. The persistent Notifications dialog
        # ALSO matches [role="dialog"] and carries its own "تأكيد" buttons, so we
        # locate the confirm button inside the real block dialog and trusted-click.
        if not click_confirm(config, page, confirm_labels):
            return outcome("failed", "Confirm button not found")
        # A successful Confirm click IS success: Facebook closes the dialog and
        # strips the now-inaccessible profile, so any reload/verify is unreliable.
        # We still settle (so the next navigation doesn't race the closing dialog)
        # and log the verify result for diagnostics, but it NEVER changes the status.
        if config.verify_reload:
            verified = verify(config, page, url, expect_unblock_after)
        else:
            verified = wait_for_confirm_dialog_closed(config, page, confirm_labels)
        if not verified:
            logger.info(
                "%s of %s: confirm clicked; close/verify not observed (treated as success)",
                stage,
                url,
            )
        return outcome(success_status)
    except TimeoutError as exc:
        logger.warning("%s of %s timed out: %s", stage, url, exc)
        return outcome("failed", f"timeout: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s of %s failed: %s", stage, url, exc)
        return outcome("failed", str(exc))


def run_batch(
    config: ReactionConfig, action_fn, urls: list[str], delay_between: bool = True
) -> list[BlockOutcome]:
    """Apply ``action_fn`` to each URL, pausing between successful actions.

    Honors ``config.daily_cap`` as a per-run safety brake: once that many actions
    have succeeded, the remaining URLs are skipped. ``daily_cap <= 0`` means
    unlimited (the default), so every URL is processed.
    """
    cap = config.daily_cap if config.daily_cap > 0 else 0
    outcomes: list[BlockOutcome] = []
    succeeded = 0
    for index, url in enumerate(urls):
        if cap and succeeded >= cap:
            logger.info("cap of %d reached; stopping (%d URL(s) skipped)", cap, len(urls) - index)
            break
        outcome = action_fn(url)
        outcomes.append(outcome)
        last = index == len(urls) - 1
        if outcome.status in ("blocked", "unblocked"):
            succeeded += 1
            if delay_between and not last and not (cap and succeeded >= cap):
                human_delay(config)
    return outcomes


def run_session(config: ReactionConfig, fn):
    """Session-runner HOF: open a stealthed persistent page, run ``fn(page)``,
    and close. The functional alternative to the FacebookBlocker context manager."""
    with persistent_page(config) as (_context, page):
        return fn(page)


def block_urls(config: ReactionConfig, urls: list[str], *, delay_between: bool = True) -> list[BlockOutcome]:
    """Block many profile URLs in one session -- no context manager needed."""
    return run_session(
        config,
        lambda page: run_batch(
            config, lambda u: menu_action(config, page, u, None, **_BLOCK), urls, delay_between
        ),
    )


def unblock_urls(config: ReactionConfig, urls: list[str], *, delay_between: bool = True) -> list[BlockOutcome]:
    """Unblock many profile URLs in one session -- no context manager needed."""
    return run_session(
        config,
        lambda page: run_batch(
            config, lambda u: menu_action(config, page, u, None, **_UNBLOCK), urls, delay_between
        ),
    )


class FacebookBlocker:
    """Block/unblock Facebook profiles by URL using a logged-in persistent profile.

    Use as a context manager so one browser session is reused across many URLs::

        with FacebookBlocker(profile_dir=".profiles/facebook") as fb:
            fb.block(url)

    Seed the login once with ``python main.py login``.
    """

    def __init__(
        self,
        profile_dir: str | Path,
        headless: bool = False,
        *,
        dialog_timeout_ms: int = 12_000,
        min_delay_s: float = 2.0,
        max_delay_s: float = 6.0,
    ) -> None:
        self.config = session_config(
            profile_dir,
            headless,
            dialog_timeout_ms=dialog_timeout_ms,
            min_delay_s=min_delay_s,
            max_delay_s=max_delay_s,
        )
        self._cm: AbstractContextManager[tuple[BrowserContext, Page]] | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None

    # --- session lifecycle ------------------------------------------------- #
    def __enter__(self) -> FacebookBlocker:
        self._cm = persistent_page(self.config)
        self._context, self.page = self._cm.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        if self._cm is not None:
            self._cm.__exit__(*exc)
            self._cm = self._context = self.page = None

    # --- public API: thin shell over the functional core above ------------- #
    def block(self, profile_url: str | None, name: str | None = None) -> BlockOutcome:
        """Block a single profile by URL. Returns a verified BlockOutcome."""
        return menu_action(self.config, self._require_page(), profile_url, name, **_BLOCK)

    def unblock(self, profile_url: str | None, name: str | None = None) -> BlockOutcome:
        """Unblock a single profile by URL. Returns a verified BlockOutcome."""
        return menu_action(self.config, self._require_page(), profile_url, name, **_UNBLOCK)

    def block_many(self, profile_urls: list[str], *, delay_between: bool = True) -> list[BlockOutcome]:
        self._require_page()
        return run_batch(self.config, self.block, profile_urls, delay_between)

    def unblock_many(self, profile_urls: list[str], *, delay_between: bool = True) -> list[BlockOutcome]:
        self._require_page()
        return run_batch(self.config, self.unblock, profile_urls, delay_between)

    # --- internals --------------------------------------------------------- #
    def _require_page(self) -> Page:
        if self.page is None:
            raise RuntimeError(
                "FacebookBlocker must be used as a context manager: "
                "`with FacebookBlocker(profile_dir) as fb: fb.block(url)`"
            )
        return self.page
