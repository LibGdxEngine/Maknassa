from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from playwright.sync_api import Error, Page, TimeoutError, sync_playwright
from playwright_stealth import Stealth
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from scraper.config import ScrapeConfig
from scraper.extractor import normalize_url_with_keys, parse_comment
from scraper.models import RawCommentCandidate, SessionStats
from scraper.storage import SQLiteStore

EXPAND_TEXT_PATTERNS = (
    "View more comments",
    "View previous comments",
    "View more replies",
    "See more replies",
    "Show more replies",
    "More replies",
    "View more",
    "عرض المزيد من التعليقات",
    "عرض التعليقات السابقة",
    "عرض المزيد من الردود",
    "عرض المزيد من الردود السابقة",
    "عرض الردود السابقة",
    "مشاهدة المزيد من الردود",
    "المزيد من الردود",
    "المزيد من التعليقات",
)

FILTER_NOTICE_PATTERNS = (
    "some comments have been filtered",
    "filtered comments",
    "تمت فلترة بعض التعليقات",
    "تم فلترة بعض التعليقات",
)

LOGIN_TEXT_PATTERNS = ("log in", "login", "تسجيل الدخول")

SORT_CONTROL_PATTERNS = (
    "most relevant",
    "all comments",
    "newest",
    "الأكثر ملاءمة",
    "كل التعليقات",
    "الأحدث",
)

ALL_COMMENTS_PATTERNS = (
    "all comments",
    "كل التعليقات",
    "جميع التعليقات",
)

NEWEST_PATTERNS = (
    "newest",
    "الأحدث",
)

COLLECT_CANDIDATES_SCRIPT = """
() => {
  const isVisible = (element) => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  };

  const normalize = (value) => (value || '')
    .replace(/[\\u200c-\\u200f\\ufeff]/g, ' ')
    .replace(/\\s+/g, ' ')
    .trim();

  const buildPath = (element) => {
    const parts = [];
    let current = element;
    while (current && current !== document.body) {
      const parent = current.parentElement;
      if (!parent) break;
      const siblings = Array.from(parent.children).filter((child) => child.tagName === current.tagName);
      const index = siblings.indexOf(current);
      parts.push(`${current.tagName.toLowerCase()}:${index}`);
      current = parent;
    }
    return parts.reverse().join('/');
  };

  const extractCommentId = (value) => {
    if (!value) return null;
    const patterns = [
      /[?&]comment_id=(\\d+)/,
      /\\/permalink\\/(\\d+)/,
      /\\/comment\\/(\\d+)/,
      /"commentID":"(\\d+)"/,
      /data-commentid="(\\d+)"/,
    ];
    for (const pattern of patterns) {
      const match = value.match(pattern);
      if (match) return match[1];
    }
    return null;
  };

  const currentUrl = new URL(window.location.href);
  const linkElements = Array.from(document.querySelectorAll('a[href]'));
  const isTimestampAnchor = (anchor) => {
    const href = anchor.getAttribute('href') || '';
    if (!href.includes('comment_id=') && !href.includes('/permalink/') && !href.includes('/comment/')) {
      return false;
    }
    let url;
    try {
      url = new URL(anchor.href, window.location.href);
    } catch {
      return false;
    }
    if (url.pathname.includes('/posts/') || url.pathname.includes('/permalink/') || url.pathname.includes('/comment/')) {
      return true;
    }
    return url.pathname === currentUrl.pathname;
  };

  const isProfileAnchor = (anchor) => {
    if (!anchor.href) return false;
    if (isTimestampAnchor(anchor)) return false;
    const text = normalize(anchor.innerText);
    if (!text || text.length > 120) return false;
    try {
      const url = new URL(anchor.href, window.location.href);
      if (url.hostname !== currentUrl.hostname) return false;
      return !url.pathname.includes('/login');
    } catch {
      return false;
    }
  };

  const findCommentRoot = (timestampAnchor) => {
    let current = timestampAnchor;
    let best = null;
    let depth = 0;
    while (current && current !== document.body && depth < 16) {
      const text = normalize(current.innerText);
      const timestampLinks = Array.from(current.querySelectorAll('a[href]')).filter(isTimestampAnchor);
      const profileLinks = Array.from(current.querySelectorAll('a[href]')).filter(isProfileAnchor);
      if (
        isVisible(current) &&
        timestampLinks.length === 1 &&
        profileLinks.length >= 1 &&
        text.length >= 8 &&
        text.length <= 1500
      ) {
        best = current;
      }
      current = current.parentElement;
      if (best && current) {
        const parentTimestampLinks = Array.from(current.querySelectorAll('a[href]')).filter(isTimestampAnchor);
        if (parentTimestampLinks.length > 1) {
          break;
        }
      }
      depth += 1;
    }
    return best;
  };

  const timestampAnchors = linkElements.filter((anchor) => isVisible(anchor) && isTimestampAnchor(anchor) && normalize(anchor.innerText));
  const rootEntries = [];
  const seen = new Set();

  for (const anchor of timestampAnchors) {
    const root = findCommentRoot(anchor);
    if (!root) continue;
    const nodeKey = root.getAttribute('id') || buildPath(root);
    if (seen.has(nodeKey)) continue;
    seen.add(nodeKey);

    const permalink = anchor.href;
    const commentId = extractCommentId(permalink) || extractCommentId(root.outerHTML) || root.getAttribute('data-commentid');
    const profileLink = Array.from(root.querySelectorAll('a[href]')).find((candidate) => isProfileAnchor(candidate) && normalize(candidate.innerText));
    const profileUrl = profileLink ? profileLink.href : null;
    const authorName = profileLink ? normalize(profileLink.innerText) : null;
      const image = root.querySelector('image[href], image[*|href], img[src]');
      const thumbnail = image ? (image.getAttribute('href') || image.getAttribute('xlink:href') || image.getAttribute('src')) : null;
      const lineCandidates = root.innerText
        .split('\\n')
        .map((value) => normalize(value))
        .filter(Boolean);

      rootEntries.push({
        node_key: nodeKey,
      outer_html: root.outerHTML,
      depth_hint: 0,
      parent_comment_id_hint: null,
      permalink_hint: permalink,
      author_name_hint: authorName,
      author_profile_url_hint: profileUrl,
        author_thumbnail_url_hint: thumbnail,
        text_hint: null,
        timestamp_text_hint: normalize(anchor.innerText),
        page_locale: document.documentElement.lang || null,
        source_url: window.location.href,
        root_path: buildPath(root),
        comment_id_hint: commentId,
        line_candidates: lineCandidates,
      });
    }

  rootEntries.sort((left, right) => left.root_path.length - right.root_path.length);
  const rootPaths = rootEntries.map((entry) => entry.root_path);

  for (const entry of rootEntries) {
    let parentPath = null;
    for (const candidatePath of rootPaths) {
      if (candidatePath === entry.root_path) continue;
      if (entry.root_path.startsWith(candidatePath) && (!parentPath || candidatePath.length > parentPath.length)) {
        parentPath = candidatePath;
      }
    }
    if (parentPath) {
      const parentEntry = rootEntries.find((candidate) => candidate.root_path === parentPath);
      if (parentEntry) {
        entry.parent_comment_id_hint = parentEntry.comment_id_hint || null;
        entry.depth_hint = parentEntry.depth_hint + 1;
      }
    }

    const ignored = new Set([
      normalize(entry.author_name_hint),
      normalize(entry.timestamp_text_hint),
      'أعجبني',
      'تعليق',
      'Like',
      'Reply',
      'حساب تم التحقق منه',
      'Verified account',
    ]);
    entry.text_hint = entry.line_candidates.find((value) => !ignored.has(value) && !/^\\d+$/.test(value) && value.length > 1) || null;
    delete entry.line_candidates;
    delete entry.root_path;
    delete entry.comment_id_hint;
  }

  return rootEntries;
}
"""


def normalize_control_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = re.sub(r"[\u200c-\u200f\ufeff]+", " ", value)
    normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
    return normalized


def is_expand_control_text(value: str | None) -> bool:
    normalized = normalize_control_text(value)
    if not normalized:
        return False
    if any(token in normalized for token in LOGIN_TEXT_PATTERNS):
        return False
    if any(token.casefold() in normalized for token in EXPAND_TEXT_PATTERNS):
        return True
    english = ("more" in normalized or "previous" in normalized) and ("comment" in normalized or "repl" in normalized)
    arabic = "المزيد" in normalized and ("تعليق" in normalized or "رد" in normalized)
    previous_arabic = "السابقة" in normalized and ("تعليق" in normalized or "رد" in normalized)
    return english or arabic or previous_arabic


def is_sort_control_text(value: str | None) -> bool:
    normalized = normalize_control_text(value)
    if not normalized:
        return False
    return any(pattern in normalized for pattern in (normalize_control_text(item) for item in SORT_CONTROL_PATTERNS))


def is_all_comments_text(value: str | None) -> bool:
    normalized = normalize_control_text(value)
    return any(pattern in normalized for pattern in (normalize_control_text(item) for item in ALL_COMMENTS_PATTERNS))


def is_newest_comments_text(value: str | None) -> bool:
    normalized = normalize_control_text(value)
    return any(pattern in normalized for pattern in (normalize_control_text(item) for item in NEWEST_PATTERNS))


def is_all_comments_description_text(value: str | None) -> bool:
    normalized = normalize_control_text(value)
    return "all comments" in normalized or "كل التعليقات" in normalized or "جميع التعليقات" in normalized


class FacebookCommentScraper:
    def __init__(self, config: ScrapeConfig, store: SQLiteStore) -> None:
        self.config = config
        self.store = store
        self.stats = SessionStats()
        self._stealth = Stealth()
        self._debug_run_dir: Path | None = None

    def run(self) -> tuple[int, SessionStats]:
        session_id = self.store.start_session(
            post_url=self.config.post_url,
            auth_mode="persistent_profile",
            profile_dir=self.config.profile_dir,
            headless=self.config.headless,
            debug_dir=self.config.debug_dir,
        )
        status = "completed"
        notes = None
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.config.profile_dir),
                    headless=self.config.headless,
                    viewport={"width": 1440, "height": 1600},
                )
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    self._stealth.apply_stealth_sync(page)
                    self._navigate(page)
                    self._initialize_debug_dir(session_id)
                    self._capture_debug_artifacts(page, "initial")
                    self._update_session_context(page, session_id)
                    self._switch_comment_sort(page, session_id)
                    self._expand_and_extract(page, session_id)
                    self._capture_debug_artifacts(page, "final")
                finally:
                    context.close()
        except Exception as exc:
            status = "failed"
            notes = str(exc)
            self.stats.failures += 1
            self.store.record_failure(session_id, "run", self.config.post_url, str(exc))
            raise
        finally:
            self.store.finish_session(session_id, status, self.stats, notes=notes)
        return session_id, self.stats

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(2),
        retry=retry_if_exception_type((TimeoutError, Error)),
        reraise=True,
    )
    def _navigate(self, page: Page) -> None:
        page.goto(self.config.post_url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout_ms)
        page.wait_for_timeout(self.config.settle_timeout_ms)
        current_url = page.url.lower()
        if "login" in current_url or "checkpoint" in current_url:
            raise RuntimeError("Reached a Facebook login or checkpoint page. Use an authorized persistent profile.")

    def _initialize_debug_dir(self, session_id: int) -> None:
        if self.config.debug_dir is None:
            return
        self._debug_run_dir = self.config.debug_dir / f"session-{session_id}"
        self._debug_run_dir.mkdir(parents=True, exist_ok=True)

    def _capture_debug_artifacts(self, page: Page, stage: str, extra: dict[str, object] | None = None) -> None:
        if self._debug_run_dir is None:
            return
        metadata = {
            "stage": stage,
            "url": page.url,
            "title": page.title(),
            "html_lang": page.locator("html").get_attribute("lang"),
        }
        if extra:
            metadata.update(extra)
        (self._debug_run_dir / f"{stage}.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        if self.config.save_html_snapshots:
            (self._debug_run_dir / f"{stage}.html").write_text(page.content(), encoding="utf-8")
        if self.config.save_screenshot:
            page.screenshot(path=str(self._debug_run_dir / f"{stage}.png"), full_page=True)

    def _detect_logged_out(self, page: Page) -> bool:
        body_text = normalize_control_text(page.locator("body").inner_text())
        return any(token in body_text for token in LOGIN_TEXT_PATTERNS)

    def _detect_filtered_comments_notice(self, page: Page) -> bool:
        body_text = normalize_control_text(page.locator("body").inner_text())
        return any(pattern in body_text for pattern in FILTER_NOTICE_PATTERNS)

    def _count_visible_comment_anchors(self, page: Page) -> int:
        return page.evaluate(
            """
            () => {
              const currentUrl = new URL(window.location.href);
              const hrefs = new Set();
              for (const anchor of document.querySelectorAll('a[href]')) {
                const text = (anchor.innerText || '').trim();
                if (!text) continue;
                const href = anchor.getAttribute('href') || '';
                if (!href.includes('comment_id=') && !href.includes('/permalink/') && !href.includes('/comment/')) continue;
                const url = new URL(anchor.href, window.location.href);
                const isTimestamp = url.pathname.includes('/posts/') || url.pathname.includes('/permalink/') || url.pathname.includes('/comment/') || url.pathname === currentUrl.pathname;
                if (!isTimestamp) continue;
                hrefs.add(url.origin + url.pathname + '?comment_id=' + (url.searchParams.get('comment_id') || ''));
              }
              return hrefs.size;
            }
            """
        )

    def _get_sort_control_text(self, page: Page) -> str | None:
        items = page.locator('button, [role="button"], a[role="button"], a[role="link"]')
        values = items.evaluate_all(
            """
            els => els
              .map(el => ((el.innerText || el.getAttribute('aria-label') || '').trim()))
              .filter(Boolean)
            """
        )
        for value in values:
            if is_sort_control_text(value):
                return value
        return None

    def _switch_comment_sort(self, page: Page, session_id: int) -> None:
        if self.config.skip_sort_switch:
            return
        before_count = self._count_visible_comment_anchors(page)
        before_filtered = self._detect_filtered_comments_notice(page)
        initial_sort_label = self._get_sort_control_text(page)
        self.store.update_session_context(
            session_id,
            sort_switch_attempted=True,
            sort_switch_succeeded=False,
            initial_sort_label=initial_sort_label,
            visible_comment_anchors_before_sort=before_count,
            filtered_comments_notice_before_sort=before_filtered,
        )
        self._capture_debug_artifacts(
            page,
            "before_sort_switch",
            extra={
                "initial_sort_label": initial_sort_label,
                "visible_comment_anchors_before_sort": before_count,
                "filtered_comments_notice_before_sort": before_filtered,
            },
        )
        try:
            if not initial_sort_label:
                raise RuntimeError("Comment sort control not found")
            sort_control = page.get_by_text(initial_sort_label, exact=False).first
            sort_control.click(timeout=5_000)
            page.wait_for_timeout(1_500)
            menu_items = page.locator('button, [role="button"], [role="menuitem"], [role="option"], a[role="link"]')
            options = menu_items.evaluate_all(
                """
                els => els
                  .map(el => ((el.innerText || el.getAttribute('aria-label') || '').trim()))
                  .filter(Boolean)
                """
            )
            matched_options = [option for option in options if is_sort_control_text(option)]
            self._capture_debug_artifacts(page, "sort_menu_open", extra={"sort_menu_options": matched_options})
            target_label = None
            for label in options:
                if is_all_comments_text(label):
                    target_label = label
                    break
            if target_label is None:
                for label in options:
                    if is_newest_comments_text(label) and is_all_comments_description_text(label):
                        target_label = label
                        break
            if target_label is None:
                raise RuntimeError("All comments option not available in sort menu")
            clicked = page.evaluate(
                """
                (targetLabel) => {
                  const normalize = (value) => (value || '')
                    .replace(/[\\u200c-\\u200f\\ufeff]/g, ' ')
                    .replace(/\\s+/g, ' ')
                    .trim()
                    .toLowerCase();
                  const target = normalize(targetLabel);
                  const visible = (element) => {
                    const style = window.getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                  };
                  const elements = Array.from(document.querySelectorAll('button, [role="button"], [role="menuitem"], [role="option"], a[role="link"]'));
                  for (const element of elements) {
                    if (!visible(element)) continue;
                    const text = normalize(element.innerText || element.getAttribute('aria-label'));
                    if (!text) continue;
                    if (text === target || text.startsWith(target + ' ') || text.startsWith(target + '\\n')) {
                      element.click();
                      return true;
                    }
                  }
                  return false;
                }
                """,
                target_label,
            )
            if not clicked:
                raise RuntimeError(f"Could not click sort option: {target_label}")
            page.wait_for_timeout(3_000)
            after_count = self._count_visible_comment_anchors(page)
            after_filtered = self._detect_filtered_comments_notice(page)
            final_sort_label = self._get_sort_control_text(page)
            self.store.update_session_context(
                session_id,
                sort_switch_succeeded=True,
                final_sort_label=final_sort_label,
                visible_comment_anchors_after_sort=after_count,
                filtered_comments_notice_after_sort=after_filtered,
            )
            self._capture_debug_artifacts(
                page,
                "after_sort_switch",
                extra={
                    "final_sort_label": final_sort_label,
                    "visible_comment_anchors_after_sort": after_count,
                    "filtered_comments_notice_after_sort": after_filtered,
                },
            )
            self._update_session_context(page, session_id)
        except Exception as exc:
            self.stats.failures += 1
            self.store.record_failure(session_id, "sort_switch", initial_sort_label, str(exc))
            self.store.update_session_context(
                session_id,
                final_sort_label=initial_sort_label,
                visible_comment_anchors_after_sort=before_count,
                filtered_comments_notice_after_sort=before_filtered,
            )

    def _update_session_context(self, page: Page, session_id: int) -> None:
        visible_anchors = self._count_visible_comment_anchors(page)
        self.stats.visible_comment_anchors = visible_anchors
        self.store.update_session_context(
            session_id,
            canonical_post_url=normalize_url_with_keys(page.url, page.url, keep_query_keys=()),
            page_locale=page.locator("html").get_attribute("lang"),
            logged_out=self._detect_logged_out(page),
            filtered_comments_notice=self._detect_filtered_comments_notice(page),
            final_sort_label=self._get_sort_control_text(page),
            visible_comment_anchors=visible_anchors,
            debug_dir=str(self._debug_run_dir) if self._debug_run_dir else None,
        )

    def _expand_and_extract(self, page: Page, session_id: int) -> None:
        seen_node_keys: set[str] = set()
        seen_comment_ids: set[str] = set()
        idle_rounds = 0

        for round_index in range(self.config.max_expand_rounds):
            click_count = self._click_expand_controls(page, session_id)
            self.stats.expansion_clicks += click_count
            candidates = self._collect_candidates(page, session_id)
            new_nodes = 0
            for candidate in candidates:
                if candidate.node_key in seen_node_keys:
                    continue
                seen_node_keys.add(candidate.node_key)
                new_nodes += 1
                self.stats.discovered_nodes += 1
                record = parse_comment(candidate)
                if record is None:
                    continue
                if record.comment_id and record.comment_id in seen_comment_ids:
                    self.stats.duplicate_comments += 1
                    continue
                if record.comment_id:
                    seen_comment_ids.add(record.comment_id)
                dedupe_key = None
                if record.comment_id is None:
                    dedupe_key = hashlib.sha1(
                        json.dumps(
                            {
                                "author_name": record.author_name,
                                "text": record.text,
                                "timestamp_text": record.timestamp_text,
                                "depth": record.depth,
                                "node_key": candidate.node_key,
                            },
                            sort_keys=True,
                        ).encode("utf-8")
                    ).hexdigest()
                self.store.upsert_comment(session_id, record, raw_dedupe_key=dedupe_key)
                self.stats.stored_comments += 1

            self._update_session_context(page, session_id)
            if click_count == 0 and new_nodes == 0:
                idle_rounds += 1
            else:
                idle_rounds = 0
            if idle_rounds >= self.config.max_idle_rounds:
                break

            scroll_distance = page.evaluate("() => Math.max(window.innerHeight * 0.9, 600)")
            page.mouse.wheel(0, int(scroll_distance))
            page.wait_for_timeout(self.config.settle_timeout_ms)
        else:
            self.store.record_failure(
                session_id,
                "expand",
                self.config.post_url,
                f"Stopped after reaching max_expand_rounds={self.config.max_expand_rounds}",
            )
            self.stats.failures += 1

    def _click_expand_controls(self, page: Page, session_id: int) -> int:
        clicked_labels = page.evaluate(
            """
            (patterns) => {
              const normalize = (value) => (value || '')
                .replace(/[\\u200c-\\u200f\\ufeff]/g, ' ')
                .replace(/\\s+/g, ' ')
                .trim()
                .toLowerCase();
              const controls = Array.from(document.querySelectorAll('button, [role="button"], a[role="button"], a[role="link"], div[tabindex="0"], span[tabindex="0"]'));
              const visible = (element) => {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
              };
              const positive = (text) => {
                if (!text) return false;
                if (text.includes('تسجيل الدخول') || text.includes('log in') || text.includes('login')) return false;
                if (patterns.some((pattern) => text.includes(pattern.toLowerCase()))) return true;
                const english = (text.includes('more') || text.includes('previous')) && (text.includes('comment') || text.includes('repl'));
                const arabic = text.includes('المزيد') && (text.includes('تعليق') || text.includes('رد'));
                const previousArabic = text.includes('السابقة') && (text.includes('تعليق') || text.includes('رد'));
                return english || arabic || previousArabic;
              };
              const clicked = [];
              for (const control of controls) {
                if (!visible(control)) continue;
                const label = normalize(control.innerText || control.getAttribute('aria-label'));
                if (!positive(label)) continue;
                try {
                  control.click();
                  clicked.push(label);
                } catch (error) {
                  clicked.push(`FAILED:${label}`);
                }
              }
              return clicked;
            }
            """,
            list(EXPAND_TEXT_PATTERNS),
        )
        clicked = 0
        for label in clicked_labels:
            if label.startswith("FAILED:"):
                self.stats.failures += 1
                self.store.record_failure(session_id, "expand", label[7:], "Element click failed")
                continue
            clicked += 1
        if clicked == 0:
            self.stats.unmatched_expand_controls += 1
        if clicked:
            page.wait_for_timeout(350)
        return clicked

    def _collect_candidates(self, page: Page, session_id: int) -> list[RawCommentCandidate]:
        try:
            raw_candidates = page.evaluate(COLLECT_CANDIDATES_SCRIPT)
        except Exception as exc:
            self.stats.failures += 1
            self.store.record_failure(session_id, "extract", self.config.post_url, str(exc))
            return []
        candidates: list[RawCommentCandidate] = []
        for item in raw_candidates:
            try:
                candidates.append(RawCommentCandidate(**item))
            except TypeError as exc:
                self.stats.failures += 1
                self.store.record_failure(session_id, "extract", str(item), str(exc))
        return candidates
