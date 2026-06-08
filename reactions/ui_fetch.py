"""In-memory reactor fetch for the Streamlit UI -- names, reaction types, avatars.

The CLI scraper (:mod:`reactions.browser`) persists reactors to SQLite but never
captures their avatar image, which the UI needs as a thumbnail. Rather than
migrate the database schema, this module does an *in-memory* fetch tuned for the
UI flow: open the post's reactions dialog, walk the per-type tabs, and collect
``{name, profile_url, avatar_url}`` per reactor, normalized and de-duplicated.

It deliberately reuses the scraper's battle-tested pieces -- ``persistent_page``,
``navigate``, ``open_reactions_dialog``, the tab enumeration/click scripts, and
``select_targets`` -- and only adds the avatar-aware collection script plus the
pure normalization seam (``build_ui_reactors`` / ``merge_reactors``), which is
unit-testable without a browser.

Sync Playwright refuses to run inside a thread that already owns a running asyncio
loop (Streamlit's script thread can have one), so :func:`in_thread` runs the
blocking work on a fresh thread that has none. Drive a fetch from Streamlit with::

    reactors = in_thread(fetch_reactors, config)
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

from playwright.sync_api import Page
from pydantic import BaseModel

from reactions._js import JS_COLLECT_LOOP, JS_HELPERS, JS_SLEEP
from reactions.browser import (
    ENUM_TABS_SCRIPT,
    navigate,
    open_reactions_dialog,
    persistent_page,
    select_reaction_tab,
    select_targets,
)
from reactions.config import ReactionConfig
from reactions.extractor import parse_reactor
from reactions.models import RawReactorCandidate

T = TypeVar("T")


class UIReactor(BaseModel):
    """One reactor as the Streamlit UI needs it: identity + reaction + thumbnail."""

    name: str | None
    profile_url: str | None
    profile_key: str  # dedup key: numeric id / username slug / normalized url
    reaction_type: str
    avatar_url: str | None = None


class FetchResult(BaseModel):
    """A fetch's reactors plus Facebook's own expected total, for a completeness meter.

    ``expected_total`` is the sum of the scraped tabs' badge counts (Facebook's own
    numbers): per-type tabs sum to the post total, an 'all'-only tab gives that
    total directly, and the 'unknown' fallback yields 0 (meter hidden). The UI
    compares it to ``len(reactors)`` so a virtualization shortfall is visible rather
    than silent -- the UI twin of :meth:`ReactionScraper._warn_on_undercount`.
    """

    reactors: list[UIReactor]
    expected_total: int = 0


# Avatar-aware twin of browser.COLLECT_TAB_SCRIPT, built from the SAME shared
# JS_COLLECT_LOOP. The only difference is the per-row extractor: for every reactor
# it also resolves the avatar image. Facebook renders a reactor as two anchors to
# the same profile -- one wraps the avatar <img>, one wraps the name text -- so we
# match avatar to name by *profile identity* (URL path + id, via the loop's keyFor),
# NOT by DOM proximity. Proximity/ancestor-climbing wrongly borrows a neighbor's
# avatar when a row has none; identity matching leaves it null (the UI shows a
# placeholder) rather than the wrong face. Among a profile's images the loop's
# avatar map prefers a CDN (scontent/fbcdn) src over reaction-badge/emoji images.
COLLECT_TAB_WITH_AVATARS_SCRIPT = (
    "async (args) => {"
    + JS_HELPERS
    + JS_SLEEP
    + JS_COLLECT_LOOP.replace(
        "__EXTRACT__",
        "{ profile_url: a.href, name: name, avatar_url: avatars.get(keyFor(a.href)) || null }",
    )
    + "}"
)


def in_thread(fn: Callable[..., T], *args, **kwargs) -> T:
    """Run ``fn(*args, **kwargs)`` on a fresh thread and return its result.

    Playwright's *sync* API raises if it detects a running asyncio event loop in
    the current thread, which Streamlit's script-runner thread can have. A brand
    new worker thread owns no loop, so the blocking browser work runs there. The
    return value is forwarded and any exception is re-raised in the caller.
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn, *args, **kwargs).result()


def build_ui_reactors(
    post_url: str, reaction_type: str, locale: str | None, rows: list[dict]
) -> list[UIReactor]:
    """Pure: raw DOM rows -> normalized, de-duplicated :class:`UIReactor` list.

    Each row is run through the existing :func:`parse_reactor` (URL canonicalization,
    profile-key derivation, non-profile rejection); rows that don't resolve to a
    real profile are dropped, the rest carry their tab's ``reaction_type`` and the
    row's ``avatar_url``. De-duplicated by ``profile_key`` (first occurrence wins).
    """
    out: list[UIReactor] = []
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
        out.append(
            UIReactor(
                name=record.name,
                profile_url=record.profile_url,
                profile_key=record.profile_key,
                reaction_type=record.reaction_type,
                avatar_url=row.get("avatar_url"),
            )
        )
    return out


def merge_reactors(per_tab: list[list[UIReactor]]) -> list[UIReactor]:
    """Pure: flatten per-tab reactor lists, de-duplicated by ``profile_key``.

    The first tab that yields a reactor wins its ``reaction_type`` (per-type tabs
    are scraped before the 'all' fallback), but a missing ``avatar_url`` is
    back-filled from a later tab that did capture one.
    """
    merged: dict[str, UIReactor] = {}
    for group in per_tab:
        for reactor in group:
            existing = merged.get(reactor.profile_key)
            if existing is None:
                merged[reactor.profile_key] = reactor
            elif existing.avatar_url is None and reactor.avatar_url:
                merged[reactor.profile_key] = existing.model_copy(
                    update={"avatar_url": reactor.avatar_url}
                )
    return list(merged.values())


def fetch_with_page(page: Page, config: ReactionConfig) -> FetchResult:
    """Open the reactions dialog on an already-navigated ``page`` and collect.

    Mirrors :meth:`ReactionScraper._scrape_all_tabs` but stays in memory and keeps
    avatars: per chosen tab, click it, collect avatar-bearing rows, normalize, then
    merge across tabs. Returns a :class:`FetchResult` carrying the merged reactors
    and Facebook's own expected total (the sum of the scraped tabs' badge counts) so
    the UI can flag a virtualization shortfall. Separated from :func:`fetch_reactors`
    so the tab-walking orchestration is unit-testable against a stub page.
    """
    summary_count = open_reactions_dialog(page, config)
    targets = select_targets(page.evaluate(ENUM_TABS_SCRIPT))
    locale = page.locator("html").get_attribute("lang")
    per_tab: list[list[UIReactor]] = []
    for index, reaction_type, badge in targets:
        if not select_reaction_tab(page, config, index, reaction_type):
            continue
        rows = page.evaluate(
            COLLECT_TAB_WITH_AVATARS_SCRIPT,
            {
                # Scroll until we've gathered this tab's badge count (or, for a
                # tab-less "All" dialog, the summary count) -- not for a fixed time.
                "target": badge or summary_count,
                "maxRounds": config.max_scroll_rounds,
                "sleepMs": 700,  # dwell long enough for a lazy-loaded batch to render
                "stableNeeded": config.max_idle_rounds,
            },
        )
        per_tab.append(build_ui_reactors(config.post_url, reaction_type, locale, rows))
    # Per-type tabs sum to the total; a tab-less "All" dialog has no badges, so fall
    # back to the count Facebook showed on the summary control we clicked.
    expected_total = max(sum(badge for _i, _t, badge in targets), summary_count)
    return FetchResult(reactors=merge_reactors(per_tab), expected_total=expected_total)


def fetch_reactors(config: ReactionConfig) -> FetchResult:
    """Open a fresh logged-in session, navigate to the post, and fetch reactors.

    The browser-driving entry point for the UI. Call it through :func:`in_thread`
    from Streamlit so the sync Playwright session never collides with Streamlit's
    event loop.
    """
    with persistent_page(config) as (_context, page):
        navigate(page, config.post_url, config)
        return fetch_with_page(page, config)
