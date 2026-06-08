"""Shared in-page JavaScript helpers, injected into every ``page.evaluate`` call.

Single source of truth for the small DOM utilities that both the scraper
(:mod:`reactions.browser`) and the block/unblock service (:mod:`reactions.service`)
need. Previously each module — and in ``service`` each individual script — re-declared
``norm`` / ``lc`` / ``visible`` inline; consolidating them here keeps the semantics
identical everywhere and avoids drift.

Compose a script by concatenating ``JS_HELPERS`` right after the arrow-function header::

    SCRIPT = "() => {" + JS_HELPERS + "  ... body ...}"

``sleep`` is intentionally *not* included: only the two async scrolling/menu scripts
need it, and they declare it locally to avoid an unused binding (and a ``const``
redeclaration) in the many scripts that don't.
"""

from __future__ import annotations

# All matching is on semantic signals (text/role/aria), never CSS classes.
JS_HELPERS = """
  const norm = (v) => (v || '').replace(/[\\u200c-\\u200f\\ufeff]/g, ' ').replace(/\\s+/g, ' ').trim();
  const lc = (v) => norm(v).toLowerCase();
  const visible = (el) => {
    if (!el) return false;
    const s = window.getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.visibility !== 'hidden' && s.display !== 'none' && r.width > 0 && r.height > 0;
  };
  const findDialog = () => {
    const ds = [...document.querySelectorAll('[role="dialog"]')].filter(visible);
    // Prefer the topmost (last-in-DOM) dialog that actually holds reaction tabs;
    // a permalink page can have other visible dialogs without tabs.
    const withTabs = ds.filter((d) => d.querySelector('[role="tab"]'));
    if (withTabs.length) return withTabs[withTabs.length - 1];
    return ds.length ? ds[ds.length - 1] : null;
  };
  const scrollContainer = (root) => {
    let best = null;
    for (const el of root.querySelectorAll('*')) {
      const s = window.getComputedStyle(el);
      if (/(auto|scroll)/.test(s.overflowY) && el.scrollHeight > el.clientHeight + 20) {
        if (!best || el.scrollHeight > best.scrollHeight) best = el;
      }
    }
    return best;
  };
  // A real reactor row anchor: a profile link inside the dialog carrying visible
  // name text (not the close button, the tabs, or an icon-only control).
  const isReactorAnchor = (a) => {
    if (!a || a.tagName !== 'A' || !a.href) return false;
    const name = norm(a.innerText);
    return !!name && name.length <= 120;
  };
  // The scrollable ancestors of `el` up to (and excluding) root's parent,
  // innermost-first -- the inner virtualized list is nearer the anchor than any
  // outer wrapper.
  const scrollableAncestors = (el, root) => {
    const out = [];
    const stop = root.parentElement;
    for (let cur = el; cur && cur !== stop; cur = cur.parentElement) {
      const s = window.getComputedStyle(cur);
      if (/(auto|scroll)/.test(s.overflowY) && cur.scrollHeight > cur.clientHeight + 20) out.push(cur);
    }
    return out;
  };
  // Ordered scroll-container candidates, best-first: scrollable ancestors of the
  // first real reactor anchor (the inner list), then the legacy largest-scrollHeight
  // pick as a backstop. Choosing by anchor beats "largest scrollHeight", which can
  // select an outer wrapper that never advances the virtualized list when scrolled.
  const scrollCandidates = (root) => {
    const cands = [];
    const anchor = [...root.querySelectorAll('a[href]')].find(isReactorAnchor);
    if (anchor) for (const c of scrollableAncestors(anchor, root)) if (!cands.includes(c)) cands.push(c);
    const legacy = scrollContainer(root);
    if (legacy && !cands.includes(legacy)) cands.push(legacy);
    return cands;
  };
"""

# The single async sleep helper, declared locally by the two scripts that scroll
# or poll inside the page (keeps it out of the synchronous scripts).
JS_SLEEP = "  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));\n"


# Virtualization-safe collect loop, shared by the CLI scraper (browser.py) and the
# UI fetch (ui_fetch.py). Facebook's "who reacted" dialog removes rows from the DOM
# once scrolled past, so capturing everyone means scrolling to the bottom while
# accumulating rows -- this loop is the single source of truth for doing that.
#
# Compose it as the body of an async page function and substitute ``__EXTRACT__``
# with a per-row object expression (in scope: ``a`` = the anchor, ``name`` = its
# normalized text, ``keyFor``, ``avatars``)::
#
#     "async (args) => {" + JS_HELPERS + JS_SLEEP
#         + JS_COLLECT_LOOP.replace("__EXTRACT__", "{ profile_url: a.href, name: name }") + "}"
#
# ``args`` carries ``target`` (the reactor count Facebook showed for this tab BEFORE
# scrolling -- the loop's primary stop condition), ``maxRounds`` (hard cap),
# ``sleepMs`` (dwell per round, long enough for a lazy-loaded batch to arrive), and
# ``stableNeeded`` (consecutive stalls tolerated near the target). The loop returns
# the de-duplicated row objects, so each call site decides its own row shape.
#
# Robustness properties (each fixes a way the old per-site loops capped at ~one DOM
# snapshot): (1) container is chosen by reactor-anchor ancestry and verified to move,
# with a drive-anyway fallback instead of a silent no-scroll return; (2) loading is
# driven to the bottom each round with real scroll + wheel events; (3) when the row
# count stalls (pinning at the exact bottom does not re-trigger Facebook's
# IntersectionObserver) it JIGGLES -- scrolls up a couple of viewports then back --
# to re-arm the loader; (4) it stops on REACHING ``target`` rather than on a timer,
# staying patient while far from target and ending only once near it (the unlinkable
# remainder) or on a hard stall guard.
JS_COLLECT_LOOP = r"""
  const dialog = findDialog();
  if (!dialog) return [];

  // Stable profile identity (path + ?id=) so avatars match by identity, not DOM
  // proximity, and tracking params don't fragment keys.
  const keyFor = (href) => {
    try {
      const u = new URL(href, location.href);
      const id = u.searchParams.get('id');
      return u.pathname.replace(/\/+$/, '') + (id ? ('?id=' + id) : '');
    } catch (e) { return href; }
  };

  // --- movement-verified container selection --------------------------------
  const candidates = scrollCandidates(dialog);
  let container = null;
  for (const c of candidates) {
    const before = c.scrollTop;
    c.scrollTop = before + Math.max(c.clientHeight * 0.3, 120);
    const moved = Math.abs(c.scrollTop - before) > 1 || c.scrollHeight > c.clientHeight + 20;
    c.scrollTop = before;
    if (moved) { container = c; break; }
  }
  // No verified container: drive the best candidate (or the dialog) anyway with
  // scrollIntoView + wheel, which advances virtualized lists even when scrollTop
  // writes are clamped -- removes the silent no-scroll cap that stopped at ~28.
  const scope = container || candidates[0] || dialog;

  const found = new Map();   // full href -> row object (shape decided by __EXTRACT__)
  const avatars = new Map(); // profile key -> avatar src (used only if the extractor needs it)
  const refreshAvatars = () => {
    for (const a of scope.querySelectorAll('a[href]')) {
      const imgs = [...a.querySelectorAll('img[src]')].filter((im) => /^https?:/i.test(im.src));
      if (!imgs.length) continue;
      const pref = imgs.find((im) => /scontent|fbcdn/i.test(im.src) && !/emoji|static\./i.test(im.src)) || imgs[0];
      const key = keyFor(a.href);
      if (key && !avatars.has(key)) avatars.set(key, pref.src);
    }
  };
  const collect = () => {
    refreshAvatars();
    for (const a of scope.querySelectorAll('a[href]')) {
      const name = norm(a.innerText);
      if (!name || name.length > 120) continue;
      if (!a.href) continue;
      if (!found.has(a.href)) found.set(a.href, (__EXTRACT__));
    }
  };

  // Nudge Facebook's infinite-scroll loader. A bare scrollTop write is sometimes
  // ignored; a scroll + wheel event on the container is what reliably re-arms it.
  const fire = () => {
    try { scope.dispatchEvent(new Event('scroll', { bubbles: true })); } catch (e) {}
    try { scope.dispatchEvent(new WheelEvent('wheel', { deltaY: 600, bubbles: true })); } catch (e) {}
  };

  // Target-driven termination: ``args.target`` is the reactor count Facebook itself
  // showed for this tab (the badge / emoji total captured BEFORE scrolling). We
  // keep scrolling until we've gathered that many -- not for a fixed time -- and
  // only fall back to a stall check for the small "near" remainder (deleted or
  // unlinkable accounts have no profile anchor, so the row set settles a few short
  // of the badge). When the row count stalls below target, pinning at the exact
  // bottom didn't re-trigger the loader, so JIGGLE (scroll up a couple of viewports,
  // then slam back) re-arms it. While we're still far from target we stay patient
  // and keep jiggling; once we're near it, a short stall ends the tab.
  const target = args.target || 0;
  const nearGap = Math.max(2, Math.floor(target * 0.05));
  const reached = () => target > 0 && found.size >= target;
  const near = () => target === 0 || found.size >= target - nearGap;
  let prev = -1, stale = 0;
  for (let i = 0; i < args.maxRounds; i++) {
    collect();
    if (reached()) break;
    stale = (found.size === prev) ? stale + 1 : 0;
    prev = found.size;
    if (stale >= 2) {
      scope.scrollTop = Math.max(0, scope.scrollHeight - scope.clientHeight * 2.2);
      fire();
      await sleep(Math.min(args.sleepMs, 300));
    }
    const rows = scope.querySelectorAll('a[href]');
    const last = rows[rows.length - 1];
    if (last) last.scrollIntoView({ block: 'end' });
    scope.scrollTop = scope.scrollHeight;
    fire();
    await sleep(args.sleepMs);
    collect();  // re-collect AFTER the wait so the freshly loaded batch is captured
    if (reached()) break;
    // Give up only once we're near the target (the rest are unlinkable), or after a
    // long hard stall that even jiggling can't move (a guard against a wrong target).
    if (near() && stale >= args.stableNeeded) break;
    if (stale >= args.stableNeeded * 4) break;
  }
  collect();
  return [...found.values()];
"""
