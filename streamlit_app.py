"""Streamlit UI: fetch a post's reactors, pick some, block them.

Flow: paste a Facebook post URL -> "Fetch reactors" opens the post's reactions
dialog and collects everyone who reacted (name + thumbnail + reaction type) ->
tick the people you want -> "Block selected" blocks exactly those profiles.

The browser work reuses the project's logged-in persistent profile, so log in once
first::

    python main.py login

then run the UI with::

    streamlit run streamlit_app.py

Playwright's sync API is driven on a fresh worker thread (``ui_fetch.in_thread``)
so it never collides with Streamlit's own event loop.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from reactions import licensing, paths
from reactions.config import ReactionConfig
from reactions.service import block_urls, session_config
from reactions.ui_fetch import UIReactor, fetch_reactors, in_thread

# reaction key -> emoji, for a compact per-reactor type badge.
REACTION_EMOJI: dict[str, str] = {
    "like": "👍",
    "love": "❤️",
    "care": "🤗",
    "haha": "😆",
    "wow": "😮",
    "sad": "😢",
    "angry": "😡",
    "all": "🔘",
    "unknown": "⚪",
}

st.set_page_config(page_title="Reactor Blocker", page_icon="🚫", layout="centered")


def _sidebar() -> dict:
    """Render the session controls and return them as a settings dict."""
    with st.sidebar:
        st.header("Session")
        st.caption(
            "Uses your saved Facebook login. If fetching hits a login wall, run "
            "`python main.py login` once in a terminal, finish signing in, then retry."
        )
        profile_dir = st.text_input("Profile dir", value=str(paths.default_profile_dir()))
        headless = st.checkbox(
            "Headless browser", value=False, help="Uncheck to watch the browser / solve checkpoints."
        )
        st.subheader("Block pacing")
        st.caption(
            "Random delay between blocks keeps the action human-paced. Lower is "
            "faster but riskier on large batches (Facebook may temporarily block "
            "the action). Set a stop-after limit below as a safety brake."
        )
        min_delay, max_delay = st.slider(
            "Seconds between blocks", min_value=2.0, max_value=60.0, value=(2.0, 6.0), step=1.0
        )
        daily_cap = st.number_input(
            "Stop after N blocks (0 = unlimited)",
            min_value=0,
            value=0,
            step=10,
            help="Optional safety brake: stop the run once this many profiles have been blocked.",
        )
    return {
        "profile_dir": profile_dir,
        "headless": headless,
        "min_delay": float(min_delay),
        "max_delay": float(max_delay),
        "daily_cap": int(daily_cap),
    }


def _fetch_config(post_url: str, settings: dict) -> ReactionConfig:
    return ReactionConfig(
        post_url=post_url,
        db_path=paths.default_db_path(),
        profile_dir=Path(settings["profile_dir"]).expanduser().resolve(),
        headless=settings["headless"],
    )


def _selected_urls() -> list[str]:
    """Profile URLs of the currently-ticked reactors (skipping any without a URL)."""
    reactors: list[UIReactor] = st.session_state.get("reactors", [])
    return [
        r.profile_url
        for r in reactors
        if r.profile_url and st.session_state.get(f"sel_{r.profile_key}", False)
    ]


def _set_all(value: bool) -> None:
    for reactor in st.session_state.get("reactors", []):
        st.session_state[f"sel_{reactor.profile_key}"] = value


def _do_fetch(post_url: str, settings: dict) -> None:
    """Run the fetch and stash the reactors (clearing any prior selection/results)."""
    with st.spinner("Opening the post and collecting reactors… (a browser window may open)"):
        result = in_thread(fetch_reactors, _fetch_config(post_url, settings))
    # Drop stale selection/outcome/consent state from a previous URL so a new
    # reactor set always starts unselected and unconfirmed (deliberate per-batch
    # consent for the irreversible block).
    for key in [k for k in st.session_state if k.startswith("sel_")]:
        del st.session_state[key]
    st.session_state["reactors"] = result.reactors
    st.session_state["expected_total"] = result.expected_total
    st.session_state.pop("outcomes", None)
    st.session_state.pop("confirm_block", None)


def _do_block(settings: dict) -> None:
    urls = _selected_urls()
    if not urls:
        st.warning("Select at least one reactor to block.")
        return
    config = session_config(
        settings["profile_dir"],
        headless=settings["headless"],
        min_delay_s=settings["min_delay"],
        max_delay_s=settings["max_delay"],
        daily_cap=settings["daily_cap"],
    )
    with st.spinner(f"Blocking {len(urls)} profile(s)… this pauses between each one."):
        st.session_state["outcomes"] = in_thread(block_urls, config, urls)
    # Require fresh confirmation before any subsequent block of a new selection.
    st.session_state.pop("confirm_block", None)


def _render_summary(reactors: list[UIReactor], expected_total: int = 0) -> None:
    counts: dict[str, int] = {}
    for reactor in reactors:
        counts[reactor.reaction_type] = counts.get(reactor.reaction_type, 0) + 1
    badges = "  ".join(
        f"{REACTION_EMOJI.get(rt, '⚪')} {rt}: {n}" for rt, n in sorted(counts.items())
    )
    captured = len(reactors)
    # When Facebook's own count (expected_total) exceeds what we captured, show the
    # shortfall explicitly and warn on a large gap -- the signature of a
    # virtualization miss -- so an incomplete fetch is never silently presented.
    if expected_total and expected_total > captured:
        missing = expected_total - captured
        st.markdown(f"**{captured} of {expected_total} reactor(s) captured**  —  {badges}")
        if missing > max(2, int(expected_total * 0.1)):
            st.warning(
                f"{missing} reactor(s) not captured. Facebook may have throttled "
                "scrolling, or some accounts are deleted/unlinkable. Try re-fetching; "
                "if it persists, raise the scroll rounds."
            )
    else:
        st.markdown(f"**{captured} reactor(s)**  —  {badges}")


def _render_reactor_row(reactor: UIReactor) -> None:
    check_col, avatar_col, info_col = st.columns([1, 1, 8], vertical_alignment="center")
    with check_col:
        st.checkbox("select", key=f"sel_{reactor.profile_key}", label_visibility="collapsed")
    with avatar_col:
        if reactor.avatar_url:
            st.image(reactor.avatar_url, width=52)
        else:
            st.markdown("### 👤")
    with info_col:
        name = reactor.name or "(no name)"
        if reactor.profile_url:
            st.markdown(f"[{name}]({reactor.profile_url})")
        else:
            st.markdown(name)
        emoji = REACTION_EMOJI.get(reactor.reaction_type, "⚪")
        st.caption(f"{emoji} {reactor.reaction_type}")


def _render_outcomes() -> None:
    outcomes = st.session_state.get("outcomes")
    if not outcomes:
        return
    blocked = sum(1 for o in outcomes if o.status == "blocked")
    failed = sum(1 for o in outcomes if o.status != "blocked")
    st.subheader("Results")
    st.markdown(f"**Blocked: {blocked}** · Failed: {failed}")
    for outcome in outcomes:
        icon = "✅" if outcome.status == "blocked" else "❌"
        detail = f" — {outcome.detail}" if outcome.detail else ""
        st.write(f"{icon} `{outcome.status}` {outcome.name or outcome.profile_url}{detail}")


def _render_activation_gate() -> None:
    """Block the app behind licence activation. Returns only once activated."""
    if licensing.is_activated():
        return
    st.title("🔑 Activate Maknassa")
    st.write(
        "Maknassa is a licensed app. Paste the licence key from your purchase "
        "confirmation to activate it on this machine."
    )
    key = st.text_input("Licence key", type="password", placeholder="XXXXXXXX-XXXX-…")
    agreed = st.checkbox(
        "I accept the End-User Licence Agreement, and I understand I run this on my "
        "own Facebook account and at my own risk."
    )
    if st.button("Activate", type="primary", disabled=not agreed):
        if not key.strip():
            st.warning("Paste your licence key first.")
        else:
            with st.spinner("Activating…"):
                result = licensing.activate(key)
            if result.activated:
                st.success(f"{result.detail} Loading…")
                st.rerun()
            else:
                st.error(result.detail)
    with st.expander("Where do I find my key, and how do I move it to another machine?"):
        st.write(
            "Your key is in the purchase confirmation email/receipt. One key activates "
            "one machine; to move it, run `maknassa license deactivate` here first, then "
            "activate on the other machine."
        )
    st.stop()


def main() -> None:
    _render_activation_gate()
    st.title("🚫 Reactor Blocker")
    st.write("Fetch everyone who reacted to a post, then block the ones you pick.")
    settings = _sidebar()

    post_url = st.text_input("Facebook post URL", placeholder="https://www.facebook.com/.../posts/...")
    if st.button("Fetch reactors", type="primary"):
        if not post_url.strip():
            st.warning("Paste a post URL first.")
        else:
            try:
                _do_fetch(post_url.strip(), settings)
            except Exception as exc:  # noqa: BLE001 - surface any browser/login error to the UI
                st.error(f"Fetch failed: {exc}")

    reactors: list[UIReactor] = st.session_state.get("reactors", [])
    if reactors:
        st.divider()
        _render_summary(reactors, st.session_state.get("expected_total", 0))
        sel_col, desel_col = st.columns(2)
        sel_col.button("Select all", on_click=_set_all, args=(True,), use_container_width=True)
        desel_col.button("Deselect all", on_click=_set_all, args=(False,), use_container_width=True)

        for reactor in reactors:
            _render_reactor_row(reactor)

        st.divider()
        selected_count = len(_selected_urls())
        confirmed = st.checkbox(
            f"I understand this will block {selected_count} selected profile(s).",
            key="confirm_block",
        )
        st.button(
            f"Block selected ({selected_count})",
            type="primary",
            disabled=not confirmed or selected_count == 0,
            on_click=_do_block,
            args=(settings,),
        )
    elif "reactors" in st.session_state:
        st.info("No reactors found for that post.")

    _render_outcomes()


# Streamlit executes this file with __name__ == "__main__" (via `streamlit run`),
# so the guard runs the UI under Streamlit while keeping a plain `import
# streamlit_app` side-effect-free.
if __name__ == "__main__":
    main()
