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
from pathlib import Path

from playwright.sync_api import Page, TimeoutError

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
  const cands = [...document.querySelectorAll('[role="button"]')]
    .filter(visible)
    .filter(isCandidate)
    .sort((x, y) => x.getBoundingClientRect().top - y.getBoundingClientRect().top);
  for (const el of cands) {
    el.scrollIntoView({ block: 'center' });
    el.click();
    await sleep(1200);
    if (menuHasMarker()) return true;
    closeMenus();
    await sleep(400);
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
        min_delay_s: float = 8.0,
        max_delay_s: float = 25.0,
    ) -> None:
        self.config = ReactionConfig(
            post_url="",
            db_path=Path("reactions.db"),
            profile_dir=Path(profile_dir).expanduser().resolve(),
            headless=headless,
            dialog_timeout_ms=dialog_timeout_ms,
            block_min_delay_s=min_delay_s,
            block_max_delay_s=max_delay_s,
        )
        self._cm = None
        self._context = None
        self.page: Page | None = None

    # --- session lifecycle ------------------------------------------------- #
    def __enter__(self) -> "FacebookBlocker":
        self._cm = persistent_page(self.config)
        self._context, self.page = self._cm.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        if self._cm is not None:
            self._cm.__exit__(*exc)
            self._cm = self._context = self.page = None

    # --- public API: the blocking "function" ------------------------------- #
    def block(self, profile_url: str, name: str | None = None) -> BlockOutcome:
        """Block a single profile by URL. Returns a verified BlockOutcome."""
        return self._menu_action(
            profile_url,
            name,
            menu_labels=BLOCK_MENU_LABELS,
            confirm_labels=BLOCK_CONFIRM_LABELS,
            success_status="blocked",
            expect_unblock_after=True,
            stage="block",
        )

    def unblock(self, profile_url: str, name: str | None = None) -> BlockOutcome:
        """Unblock a single profile by URL. Returns a verified BlockOutcome."""
        return self._menu_action(
            profile_url,
            name,
            menu_labels=UNBLOCK_LABELS,
            confirm_labels=UNBLOCK_CONFIRM_LABELS,
            success_status="unblocked",
            expect_unblock_after=False,
            stage="unblock",
        )

    def block_many(self, profile_urls: list[str], *, delay_between: bool = True) -> list[BlockOutcome]:
        return self._many(profile_urls, self.block, delay_between)

    def unblock_many(self, profile_urls: list[str], *, delay_between: bool = True) -> list[BlockOutcome]:
        return self._many(profile_urls, self.unblock, delay_between)

    # --- internals --------------------------------------------------------- #
    def _many(self, urls, action_fn, delay_between) -> list[BlockOutcome]:
        outcomes: list[BlockOutcome] = []
        for index, url in enumerate(urls):
            outcome = action_fn(url)
            outcomes.append(outcome)
            last = index == len(urls) - 1
            if delay_between and not last and outcome.status in ("blocked", "unblocked"):
                self._human_delay()
        return outcomes

    def _require_page(self) -> Page:
        if self.page is None:
            raise RuntimeError(
                "FacebookBlocker must be used as a context manager: "
                "`with FacebookBlocker(profile_dir) as fb: fb.block(url)`"
            )
        return self.page

    def _menu_action(
        self,
        profile_url: str,
        name: str | None,
        *,
        menu_labels,
        confirm_labels,
        success_status: str,
        expect_unblock_after: bool,
        stage: str,
    ) -> BlockOutcome:
        """Shared profile-menu flow for both block and unblock.

        Native (trusted-event) clicks: Facebook ignores synthetic JS clicks on the
        confirm button, so Block/Unblock + Confirm go through Playwright's real
        input. Targeting the menu item / button by EXACT accessible name avoids
        the Unblock ("إلغاء الحظر") and Cancel ("إلغاء حظر <name>") controls whose
        names merely contain "حظر".
        """
        page = self._require_page()
        url = normalize_profile_url(profile_url, "https://www.facebook.com/") or profile_url
        key = extract_profile_id(url) or url or profile_url

        def outcome(status: str, detail: str | None = None) -> BlockOutcome:
            return BlockOutcome(profile_key=key, name=name, profile_url=url, status=status, detail=detail)

        if not url:
            return outcome("failed", "no profile url")
        try:
            self._load_profile(page, url)
            if not self._open_more_menu(page):
                return outcome("failed", "profile actions menu not found")

            if not self._native_click_by_name(page, "menuitem", menu_labels):
                return outcome("failed", f"{stage} menu item not found")

            # The confirmation dialog appears now. The persistent Notifications
            # dialog ALSO matches [role="dialog"] and carries its own "تأكيد"
            # buttons, so we locate the confirm button inside the real block
            # dialog (skipping Notifications) and trusted-click it.
            if not self._click_confirm(page, confirm_labels):
                return outcome("failed", "Confirm button not found")
            page.wait_for_timeout(1800)

            if self._verify(page, url, expect_unblock_after):
                return outcome(success_status)
            logger.warning("%s of %s: confirm clicked but not verified", stage, url)
            return outcome("failed", f"confirm clicked but {stage} not verified")
        except TimeoutError as exc:
            logger.warning("%s of %s timed out: %s", stage, url, exc)
            return outcome("failed", f"timeout: {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s of %s failed: %s", stage, url, exc)
            return outcome("failed", str(exc))

    def _load_profile(self, page: Page, url: str) -> None:
        """Navigate, let the profile shell hydrate, and dismiss overlays.

        Waiting for ``networkidle`` makes the "..." action bar reliably present;
        pressing Escape dismisses the persistent Notifications flyout, which can
        otherwise overlay the action bar and make the menu look "not found".
        """
        navigate(page, url, self.config)
        try:
            page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:  # noqa: BLE001 - Facebook streams; fall back to a fixed wait
            pass
        page.wait_for_timeout(2_000)
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:  # noqa: BLE001
            pass

    def _click_confirm(self, page: Page, confirm_labels, attempts: int = 16) -> bool:
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
                element.click(timeout=self.config.dialog_timeout_ms)
                return True
            page.wait_for_timeout(500)
        return False

    def _native_click_by_name(self, scope, role: str, labels) -> bool:
        """Trusted Playwright click on the first `role` element under `scope` whose
        EXACT accessible name matches one of `labels` (page-wide or within a
        dialog Locator). Exact names avoid the Unblock/Cancel controls."""
        for label in labels:
            loc = scope.get_by_role(role, name=label, exact=True)
            try:
                if loc.count() > 0:
                    loc.first.click(timeout=self.config.dialog_timeout_ms)
                    return True
            except Exception:  # noqa: BLE001 - try the next label
                continue
        return False

    def _open_more_menu(self, page: Page) -> bool:
        """Open the profile actions menu (the one containing Block/Report). The
        action bar hydrates asynchronously, so retry a few times with waits."""
        args = {
            "labels": list(MORE_BUTTON_LABELS),
            "distractors": list(MORE_DISTRACTOR_TERMS),
            "markers": list(BLOCK_MENU_LABELS) + list(UNBLOCK_LABELS) + list(REPORT_LABELS),
        }
        for attempt in range(4):
            if page.evaluate(_OPEN_ACTIONS_MENU_SCRIPT, args):
                page.wait_for_timeout(400)
                return True
            # Dismiss any overlay (Notifications flyout) and let the bar hydrate.
            try:
                page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(2_000)
        return False

    def _verify(self, page: Page, url: str, expect_unblock_after: bool) -> bool:
        """Reload the profile and infer block state from the actions menu.

        A *blocked* profile renders a stripped page whose "..." menu either offers
        Unblock, no longer offers Block, or won't open at all -- so a block is
        confirmed by any of those. An unblock is confirmed when the menu opens and
        offers Block again (and not Unblock).
        """
        try:
            self._load_profile(page, url)
            opened = self._open_more_menu(page)
            items = page.evaluate(_DUMP_MENU_ITEMS_SCRIPT) if opened else []
            has_unblock = any(matches_any(it, UNBLOCK_LABELS) for it in items)
            has_block = any(
                matches_any(it, BLOCK_MENU_LABELS) and not matches_any(it, UNBLOCK_LABELS)
                for it in items
            )
            if expect_unblock_after:  # after a BLOCK
                return has_unblock or (opened and not has_block) or (not opened)
            return opened and has_block and not has_unblock  # after an UNBLOCK
        except Exception as exc:  # noqa: BLE001
            logger.warning("verify failed for %s: %s", url, exc)
            return False

    def _human_delay(self) -> None:
        time.sleep(random.uniform(self.config.block_min_delay_s, self.config.block_max_delay_s))
