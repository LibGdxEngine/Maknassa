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
"""

# The single async sleep helper, declared locally by the two scripts that scroll
# or poll inside the page (keeps it out of the synchronous scripts).
JS_SLEEP = "  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));\n"
