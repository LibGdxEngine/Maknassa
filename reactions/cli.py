from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from pathlib import Path

from reactions import paths
from reactions.blocker import ProfileBlocker
from reactions.browser import (
    ReactionScraper,
    dump_inspection,
    login_flow,
    write_inspection,
)
from reactions.config import ReactionConfig
from reactions.selectors import REACTION_LABELS
from reactions.storage import SQLiteStore

VALID_REACTIONS = set(REACTION_LABELS) | {"all", "unknown"}


def _resolve_db_path(value: str | None) -> Path:
    """Explicit ``--db-path`` (resolved) or the per-user default location."""
    return Path(value).expanduser().resolve() if value else paths.default_db_path()


def _resolve_profile_dir(value: str | None) -> Path:
    """Explicit ``--profile-dir`` (resolved) or the per-user default location."""
    return Path(value).expanduser().resolve() if value else paths.default_profile_dir()


def _add_verbose(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Log INFO-level progress (warnings/errors always show)",
    )


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("post_url", help="Facebook post URL")
    parser.add_argument(
        "--db-path", default=None, help="SQLite database path (default: per-user data dir)"
    )
    parser.add_argument(
        "--profile-dir",
        default=None,
        help="Persistent Playwright profile dir (default: per-user data dir; login persists here)",
    )
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    _add_verbose(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reactions",
        description="Scrape Facebook post reactions and selectively block reactors.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="One-time: open Facebook headed and wait for you to log in")
    login.add_argument(
        "--profile-dir",
        default=None,
        help="Persistent Playwright profile dir (default: per-user data dir; login persists here)",
    )
    login.add_argument("--timeout", type=int, default=300, help="Seconds to wait for login")
    _add_verbose(login)

    scrape = sub.add_parser("scrape", help="Collect reactors (per reaction type) into SQLite")
    _add_common(scrape)
    scrape.add_argument("--max-idle-rounds", type=int, default=3)
    scrape.add_argument("--max-scroll-rounds", type=int, default=200)

    block = sub.add_parser("block", help="Block a reaction category or named people (dry-run by default)")
    _add_common(block)
    block.add_argument(
        "--reaction",
        default="",
        help="Comma-separated reaction types to target, e.g. angry,haha",
    )
    block.add_argument("--name", action="append", default=[], help="Target by (partial) name; repeatable")
    block.add_argument("--all", action="store_true", help="Target every scraped reactor for this post")
    block.add_argument("--execute", action="store_true", help="Actually block (default is a dry-run preview)")
    block.add_argument("--no-confirm", action="store_true", help="Skip the per-person prompt when executing")
    block.add_argument("--include-blocked", action="store_true", help="Re-include already-blocked reactors")
    block.add_argument(
        "--daily-cap", type=int, default=0, help="Max blocks before stopping (0 = unlimited)"
    )
    block.add_argument("--min-delay", type=float, default=2.0, help="Min seconds between blocks")
    block.add_argument("--max-delay", type=float, default=6.0, help="Max seconds between blocks")

    unblock = sub.add_parser("unblock", help="Unblock previously-blocked reactors (dry-run by default)")
    _add_common(unblock)
    unblock.add_argument("--reaction", default="", help="Comma-separated reaction types to target")
    unblock.add_argument("--name", action="append", default=[], help="Target by (partial) name; repeatable")
    unblock.add_argument("--all", action="store_true", help="Target every blocked reactor for this post")
    unblock.add_argument("--execute", action="store_true", help="Actually unblock (default is a dry-run preview)")
    unblock.add_argument("--no-confirm", action="store_true", help="Skip the per-person prompt when executing")

    def _add_url_action(name: str, verb: str) -> argparse.ArgumentParser:
        parser_ = sub.add_parser(name, help=f"{verb.capitalize()} profile URL(s) directly (no scrape/DB)")
        parser_.add_argument("profile_urls", nargs="+", help=f"Profile URL(s) to {verb}")
        parser_.add_argument(
            "--profile-dir",
            default=None,
            help="Persistent Playwright profile dir (default: per-user data dir)",
        )
        parser_.add_argument("--headless", action="store_true", help="Run browser headless")
        parser_.add_argument("--execute", action="store_true", help=f"Actually {verb} (default is a dry-run)")
        _add_verbose(parser_)
        return parser_

    block_url = _add_url_action("block-url", "block")
    block_url.add_argument("--min-delay", type=float, default=2.0, help="Min seconds between blocks")
    block_url.add_argument("--max-delay", type=float, default=6.0, help="Max seconds between blocks")
    block_url.add_argument(
        "--daily-cap", type=int, default=0, help="Max blocks before stopping (0 = unlimited)"
    )
    _add_url_action("unblock-url", "unblock")

    inspect = sub.add_parser("inspect", help="Dump live DOM roles/aria-labels to confirm selectors")
    _add_common(inspect)
    inspect.add_argument("--profile-url", default=None, help="Also dump a profile's action buttons/menu")
    inspect.add_argument("--out", default=None, help="Write the JSON report to this path")

    lic = sub.add_parser("license", help="Activate, check, or release your Maknassa licence")
    lic.add_argument("action", choices=["activate", "status", "deactivate"])
    lic.add_argument("key", nargs="?", default=None, help="Licence key (required for activate)")
    _add_verbose(lic)

    return parser


def _config_from_args(args: argparse.Namespace) -> ReactionConfig:
    return ReactionConfig(
        post_url=args.post_url,
        db_path=_resolve_db_path(args.db_path),
        profile_dir=_resolve_profile_dir(args.profile_dir),
        headless=bool(args.headless),
        max_idle_rounds=getattr(args, "max_idle_rounds", 3),
        max_scroll_rounds=getattr(args, "max_scroll_rounds", 200),
        dry_run=not getattr(args, "execute", False),
        confirm_each=not getattr(args, "no_confirm", False),
        daily_cap=getattr(args, "daily_cap", 0),
        block_min_delay_s=getattr(args, "min_delay", 2.0),
        block_max_delay_s=getattr(args, "max_delay", 6.0),
    )


def _cmd_scrape(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    store = SQLiteStore(config.db_path)
    scraper = ReactionScraper(config, store)
    session_id, stats = scraper.run()
    print(
        f"session_id={session_id} stored={stats.stored_reactors} "
        f"duplicates={stats.duplicate_reactors} discovered_rows={stats.discovered_rows} "
        f"failures={stats.failures}"
    )
    if stats.per_type_counts:
        print("per reaction type (captured / reacted):")
        for reaction_type, count in sorted(stats.per_type_counts.items()):
            expected = stats.per_type_expected.get(reaction_type)
            if expected and expected != count:
                gap = expected - count
                print(f"  {reaction_type:8} {count}/{expected}  ({gap} with no linkable profile)")
            else:
                print(f"  {reaction_type:8} {count}")
    return 0


def _cmd_block(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    store = SQLiteStore(config.db_path)

    reaction_types = [r.strip().lower() for r in args.reaction.split(",") if r.strip()]
    for reaction in reaction_types:
        if reaction not in VALID_REACTIONS:
            print(f"warning: unknown reaction type '{reaction}' (valid: {sorted(VALID_REACTIONS)})")
    if not reaction_types and not args.name and not args.all:
        print("Refusing to target everyone implicitly. Pass --reaction, --name, or --all.")
        return 2

    targets = store.fetch_reactors(
        post_url=config.post_url,
        reaction_types=reaction_types or None,
        names=args.name or None,
        include_blocked=args.include_blocked,
    )
    if not targets:
        print("No matching reactors found. Run `scrape` first, or relax the filters.")
        return 0

    blocker = ProfileBlocker(config, store)
    if config.dry_run:
        print(f"DRY RUN — {len(targets)} reactor(s) WOULD be blocked (pass --execute to act):")
        for outcome in blocker.preview(targets):
            print(f"  [{outcome.detail or '?':8}] {outcome.name or '(no name)'}  {outcome.profile_url}")
        print("\nNothing was blocked. Re-run with --execute to perform the blocks.")
        return 0

    cap_note = f"cap {config.daily_cap}" if config.daily_cap > 0 else "no cap"
    print(f"EXECUTING blocks for {len(targets)} reactor(s) ({cap_note})...")
    outcomes = blocker.execute(targets)
    blocked = sum(1 for o in outcomes if o.status == "blocked")
    failed = sum(1 for o in outcomes if o.status == "failed")
    skipped = sum(1 for o in outcomes if o.status == "skipped")
    for outcome in outcomes:
        print(f"  {outcome.status:8} {outcome.name or '(no name)'}  {outcome.detail or ''}")
    print(f"\nblocked={blocked} skipped={skipped} failed={failed}")
    return 0


def _cmd_login(args: argparse.Namespace) -> int:
    config = ReactionConfig(
        post_url="",
        db_path=_resolve_db_path(None),
        profile_dir=_resolve_profile_dir(args.profile_dir),
        headless=False,
    )
    c_user = login_flow(config, timeout_s=args.timeout)
    if c_user:
        print(f"Logged in (c_user={c_user}). Session saved to {config.profile_dir}")
        return 0
    print("Login not detected before timeout. Re-run `login` and finish signing in.")
    return 1


def _cmd_unblock(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    store = SQLiteStore(config.db_path)

    reaction_types = [r.strip().lower() for r in args.reaction.split(",") if r.strip()]
    if not reaction_types and not args.name and not args.all:
        print("Refusing to target everyone implicitly. Pass --reaction, --name, or --all.")
        return 2

    targets = store.fetch_reactors(
        post_url=config.post_url,
        reaction_types=reaction_types or None,
        names=args.name or None,
        only_blocked=True,
    )
    if not targets:
        print("No blocked reactors match. (Only rows marked blocked can be unblocked.)")
        return 0

    blocker = ProfileBlocker(config, store)
    if config.dry_run:
        print(f"DRY RUN — {len(targets)} reactor(s) WOULD be unblocked (pass --execute to act):")
        for outcome in blocker.preview(targets):
            print(f"  [{outcome.detail or '?':8}] {outcome.name or '(no name)'}  {outcome.profile_url}")
        print("\nNothing was unblocked. Re-run with --execute to perform the unblocks.")
        return 0

    print(f"EXECUTING unblocks for {len(targets)} reactor(s)...")
    outcomes = blocker.execute_unblock(targets)
    unblocked = sum(1 for o in outcomes if o.status == "unblocked")
    failed = sum(1 for o in outcomes if o.status == "failed")
    skipped = sum(1 for o in outcomes if o.status == "skipped")
    for outcome in outcomes:
        print(f"  {outcome.status:9} {outcome.name or '(no name)'}  {outcome.detail or ''}")
    print(f"\nunblocked={unblocked} skipped={skipped} failed={failed}")
    return 0


def _print_url_outcomes(outcomes, success: str) -> None:
    for outcome in outcomes:
        print(f"  {outcome.status:9} {outcome.profile_url}  {outcome.detail or ''}")
    done = sum(1 for o in outcomes if o.status == success)
    failed = sum(1 for o in outcomes if o.status == "failed")
    print(f"\n{success}={done} failed={failed}")


def _cmd_block_url(args: argparse.Namespace) -> int:
    from reactions.service import block_urls, session_config

    urls = args.profile_urls
    if not args.execute:
        print(f"DRY RUN — would block {len(urls)} profile(s) (pass --execute to act):")
        for url in urls:
            print(f"  {url}")
        return 0
    config = session_config(
        _resolve_profile_dir(args.profile_dir),
        headless=args.headless,
        min_delay_s=args.min_delay,
        max_delay_s=args.max_delay,
        daily_cap=args.daily_cap,
    )
    outcomes = block_urls(config, urls)
    _print_url_outcomes(outcomes, "blocked")
    return 0


def _cmd_unblock_url(args: argparse.Namespace) -> int:
    from reactions.service import session_config, unblock_urls

    urls = args.profile_urls
    if not args.execute:
        print(f"DRY RUN — would unblock {len(urls)} profile(s) (pass --execute to act):")
        for url in urls:
            print(f"  {url}")
        return 0
    config = session_config(_resolve_profile_dir(args.profile_dir), headless=args.headless)
    outcomes = unblock_urls(config, urls)
    _print_url_outcomes(outcomes, "unblocked")
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    report = dump_inspection(config, profile_url=args.profile_url)
    write_inspection(report, Path(args.out).expanduser().resolve() if args.out else None)
    return 0


def _cmd_license(args: argparse.Namespace) -> int:
    from reactions import licensing

    if args.action == "activate":
        result = licensing.activate(args.key or "")
        print(result.detail)
        return 0 if result.activated else 1
    if args.action == "deactivate":
        ok = licensing.deactivate()
        print("Licence released for this machine." if ok else "No active licence to release.")
        return 0
    status = licensing.status()  # "status"
    line = status.detail
    if status.key_masked:
        line += f"  (key {status.key_masked})"
    if status.last_validated_at:
        line += f"  last validated {status.last_validated_at}"
    print(line)
    return 0 if status.activated else 1


# Command dispatch as data: subcommand name -> handler. Replaces the if/elif chain.
_COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "login": _cmd_login,
    "scrape": _cmd_scrape,
    "block": _cmd_block,
    "unblock": _cmd_unblock,
    "block-url": _cmd_block_url,
    "unblock-url": _cmd_unblock_url,
    "inspect": _cmd_inspect,
    "license": _cmd_license,
}

# Commands that drive the browser are gated behind an active licence; `license`
# (managing the key itself) is always allowed.
_UNGATED_COMMANDS = frozenset({"license"})


def _require_license(command: str) -> bool:
    from reactions import licensing

    if command in _UNGATED_COMMANDS or licensing.is_activated():
        return True
    print(
        "This copy of Maknassa isn't activated. Run "
        "`maknassa license activate <key>` to activate it "
        f"(or set {licensing.DEV_BYPASS_ENV}=1 for development)."
    )
    return False


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    level = logging.INFO if getattr(args, "verbose", False) else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    handler = _COMMANDS.get(args.command)
    if handler is None:
        return 1
    if not _require_license(args.command):
        return 3
    return handler(args)
