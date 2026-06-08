# Maknassa

A **self-hosted desktop tool** to review and moderate the people who reacted to
your Facebook post. It runs on **your own machine** with **your own browser
login** — your session never leaves your computer.

> Maknassa is an independent community-moderation tool for creators. It is not
> affiliated with or endorsed by Facebook/Meta. Using browser automation may
> violate a platform's terms of service; you use it on your own account, at your
> own risk. See [`EULA.md`](EULA.md).

---

## Contents

- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Data & configuration](#data--configuration)
- [Run from source (development)](#run-from-source-development)
- [Licensing](#licensing)
- [Building the desktop app](#building-the-desktop-app)
- [Continuous integration](#continuous-integration)
- [Project layout](#project-layout)
- [Tests, types & lint](#tests-types--lint)
- [Roadmap](#roadmap)

---

## How it works

Log in once into a persistent browser profile, paste a post URL, review everyone
who reacted (name, avatar, reaction), tick the accounts you want, and block them
— with human-paced delays and an optional cap.

There are two front-ends over the same core:

- **Desktop app** (`maknassa-gui`) — the Streamlit UI in a native window.
- **CLI** (`maknassa`) — `login`, `scrape`, `block`, `unblock`, `block-url`,
  `unblock-url`, `inspect`, `license`.

Because it drives a real, logged-in browser session, the work stays on your
machine: there is no server, and your Facebook session/cookies are never
uploaded anywhere. The only network call Maknassa itself makes is the licence
check (see [Licensing](#licensing)).

---

## Architecture

```
┌─────────────────────────────┐     ┌──────────────────────────────┐
│  maknassa-gui (desktop.py)  │     │   maknassa (cli.py)          │
│  pywebview native window    │     │   argparse subcommands       │
│        │                    │     │        │                     │
│        ▼ localhost:PORT     │     │        │                     │
│  Streamlit server (child    │     │        │                     │
│  process, streamlit_app.py) │     │        │                     │
└────────┬────────────────────┘     └────────┬─────────────────────┘
         │                                    │
         ▼                                    ▼
        ┌───────────────────────────────────────────┐
        │  reactions/ core (shared, in-process)      │
        │  browser · service · blocker · extractor · │
        │  selectors · storage · ui_fetch · config   │
        │      │                                     │
        │      ▼  Playwright (sync API + stealth)    │
        │  persistent Chromium profile  ── SQLite    │
        └───────────────────────────────────────────┘
```

- **Desktop shell** (`reactions/desktop.py`): picks a free localhost port, starts
  Streamlit in a **child process** (so Streamlit's signal handlers get a real main
  thread and a PyInstaller-frozen build can re-exec itself), waits for it to come
  up, then opens it in a `pywebview` window. Closing the window stops the server.
- **Streamlit UI** (`streamlit_app.py`): the same UI you can also run directly.
  Playwright's sync API is driven on a worker thread (`reactions/ui_fetch.in_thread`)
  so it never collides with Streamlit's event loop.
- **Core** (`reactions/`): the scraping/blocking logic. Pure seams
  (`collect_records`, `select_targets`, the `matches_any` predicates,
  `build_fetch_query`) are unit-tested without a browser; the effectful browser
  work goes through one stealthed, persistent-profile Chromium context
  (`reactions/browser.persistent_page`).

---

## Data & configuration

All mutable state lives under a **per-user data directory** (never inside the app
bundle), resolved by `reactions/paths.py` via `platformdirs`:

| Item             | Location (default)                          |
| ---------------- | ------------------------------------------- |
| SQLite store     | `<data>/data/reactions.db`                  |
| Browser profiles | `<data>/profiles/<account>/`                |
| Licence token    | `<config>/license.json`                     |

Where `<data>` / `<config>` are the OS conventions:

| OS      | `<data>`                              | `<config>`                       |
| ------- | ------------------------------------- | -------------------------------- |
| Linux   | `~/.local/share/Maknassa`             | `~/.config/Maknassa`             |
| macOS   | `~/Library/Application Support/Maknassa` | same as `<data>`               |
| Windows | `%LOCALAPPDATA%\Maknassa`             | `%LOCALAPPDATA%\Maknassa`        |

### Environment variables

| Variable                 | Effect                                                                 |
| ------------------------ | ---------------------------------------------------------------------- |
| `MAKNASSA_DATA_DIR`      | Relocate **all** data under one folder (portable install / tests). Config then lives at `<dir>/config`. |
| `MAKNASSA_DEV=1`         | Bypass the licence gate (development).                                  |
| `MAKNASSA_NO_WINDOW=1`   | Desktop launcher serves the UI only and prints the URL (no GUI window). |
| `MAKNASSA_GUI_PORT`      | Pin the desktop server port instead of choosing a free one.            |
| `MAKNASSA_LS_API`        | Override the Lemon Squeezy API base (for a test endpoint).             |
| `PLAYWRIGHT_BROWSERS_PATH` | Set automatically by the frozen app to the bundled Chromium.        |

CLI `--db-path` / `--profile-dir` override the defaults per command; with no flag
they fall back to the per-user locations above.

---

## Run from source (development)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

export MAKNASSA_DEV=1          # bypass the licence gate while developing
python main.py login           # one-time: sign in to Facebook in the opened browser
python -m reactions.desktop    # launch the desktop UI in a window
# …or run the UI directly:
streamlit run streamlit_app.py
```

CLI examples:

```bash
python main.py scrape  "https://www.facebook.com/.../posts/..."        # collect reactors
python main.py block   "https://www.facebook.com/.../posts/..." --reaction angry   # dry-run preview
python main.py block   "https://www.facebook.com/.../posts/..." --reaction angry --execute
python main.py block-url "https://www.facebook.com/someone" --execute  # block a profile URL directly
```

`block`/`unblock` are **dry-run by default**; pass `--execute` to act. A randomized
delay between actions keeps things human-paced; `--daily-cap N` (0 = unlimited)
is a safety brake.

---

## Licensing

Maknassa is a licensed app, gated through **Lemon Squeezy**'s License API.

### For users

```bash
maknassa license activate <YOUR-KEY>   # bind this machine
maknassa license status                # check activation
maknassa license deactivate            # release this machine (to move the key)
```

The desktop UI shows an activation screen on first run (key + EULA acceptance).
One key activates one machine; deactivate to move it. `MAKNASSA_DEV=1` bypasses
the gate during development.

### How the gate works (`reactions/licensing.py`)

- **Activation** registers a per-machine *instance* (a non-reversible id derived
  from the machine) against the licence key, and stores
  `{license_key, instance_id, last_validated_at, status}` in `license.json`.
- **Offline tolerance**: after a successful online validation the app trusts the
  cached token for a grace window (`GRACE_DAYS = 7`) and only re-checks online
  past a recheck interval (`RECHECK_DAYS = 1`). A brief outage won't lock a buyer
  out; an explicit revoke/refund/expiry clears the token.
- **No new dependency / no secrets**: it talks to the public licence endpoints
  with stdlib `urllib`; the key itself is the credential.

> Offline-tolerant ≠ offline-cryptographic. Lemon Squeezy validation is online
> (HMAC). True offline-crypto licences would need a provider like Keygen — out of
> scope for the MVP.

### For the seller (setup checklist)

1. Create a Lemon Squeezy store and a product with **license keys** enabled.
2. Sell/issue keys; buyers run `maknassa license activate <key>`.
3. (Optional) Point `MAKNASSA_LS_API` at a sandbox endpoint to test activation
   without real keys.

---

## Building the desktop app

Produces a one-folder bundle in `dist/maknassa/` (the `maknassa-gui` executable +
an `_internal/` folder) with **Chromium bundled**, so end-users need no separate
`playwright install`.

```bash
bash packaging/build.sh                              # Linux/macOS
powershell -ExecutionPolicy Bypass -File packaging\build.ps1   # Windows
```

What the build does:

1. `pip install -e ".[build]"` (adds PyInstaller).
2. `playwright install chromium` into `packaging/ms-playwright` (bundled into the app).
3. `pyinstaller packaging/maknassa.spec` → `dist/maknassa/`.

At runtime the frozen launcher points `PLAYWRIGHT_BROWSERS_PATH` at the bundled
Chromium and serves `streamlit_app.py` from the bundle root.

> **First build per platform:** Streamlit is lazy-import-heavy. The spec already
> `collect_all`s the known packages; if the *first* build on a new OS hits a
> `ModuleNotFoundError` at runtime, add that module to `hiddenimports` in
> [`packaging/maknassa.spec`](packaging/maknassa.spec). This is the one expected
> manual step of a Streamlit freeze.

The bundle is large (~150 MB Chromium + Streamlit/pandas/pyarrow). `build/`,
`dist/`, and `packaging/ms-playwright/` are git-ignored.

---

## Continuous integration

[`.github/workflows/build.yml`](.github/workflows/build.yml) builds on tag
(`v*`) or manual dispatch, across an `ubuntu` / `macos` / `windows` matrix:
install → `pytest` + `mypy` → `build.sh`/`build.ps1` → upload each `dist/maknassa`
as an artifact.

Deferred for a public launch (commented in the workflow): Windows Authenticode
signing, macOS codesign + notarization, and installers (Inno Setup / DMG /
AppImage). Until then artifacts are unsigned; ship the OS "open anyway" note for
early users.

---

## Project layout

```
main.py                     CLI entry shim -> reactions.cli:main
streamlit_app.py            Streamlit UI (also bundled into the desktop app)
pyproject.toml              packaging metadata, entry points, mypy/ruff config
EULA.md                     end-user licence agreement
reactions/
  cli.py                    argparse subcommands (incl. `license`) + licence gate
  desktop.py                pywebview + child-process Streamlit launcher (maknassa-gui)
  licensing.py              Lemon Squeezy activation/validation, offline grace
  paths.py                  per-user data/config locations (platformdirs)
  browser.py                Playwright scraper + persistent_page context manager
  service.py                by-URL block/unblock functional core + FacebookBlocker
  blocker.py                DB-driven orchestration (dry-run, cap, delays)
  extractor.py selectors.py storage.py models.py ui_fetch.py config.py _js.py
packaging/
  maknassa.spec             PyInstaller one-folder spec
  build.sh / build.ps1      build wrappers (install Chromium + freeze)
.github/workflows/build.yml 3-OS matrix build
tests/                      pytest suite (fully mocked; conftest isolates data dir)
```

---

## Tests, types & lint

```bash
pytest          # unit tests (all mocked; no real browser/network)
mypy reactions/ # type check (clean)
ruff check .    # lint (clean)
```

Tests run in seconds with no external dependencies. `tests/conftest.py` sets
`MAKNASSA_DEV=1` and a throwaway `MAKNASSA_DATA_DIR` so the suite never touches a
real data dir or needs a licence.

---

## Roadmap

Shipped (MVP): per-user data dirs, packaging metadata, desktop shell, Lemon
Squeezy licence gate, 3-OS CI.

Deferred follow-ups:

- **Multi-account profiles** — make profile/session a first-class per-account object.
- **Auto-update** — version check + download/replace flow.
- **Code-signing & notarization** — Windows Authenticode, macOS Developer ID.
- **Installers** — Inno Setup (Windows), DMG (macOS), AppImage (Linux).
- **(Venture option)** a Graph-API Page-moderation product — the durable, ToS-clean play.
```
