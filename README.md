# Maknassa

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Electron](https://img.shields.io/badge/electron-latest-47848f.svg)](https://www.electronjs.org/)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](https://www.python.org/)

A **free, open-source desktop app** to review and moderate the people who reacted
to your Facebook post. It runs on **your own computer** with **your own browser
login** — your session never leaves your machine.

> Maknassa is an independent community-moderation tool for creators. It is **not**
> affiliated with or endorsed by Facebook/Meta. Using browser automation may
> violate a platform's terms of service; you use it on your own account, at your
> own risk. See [`DISCLAIMER.md`](DISCLAIMER.md).

---

## Download & install

> **Note:** download links point at the latest release. If one 404s (e.g. before the
> first release is published), grab the file from the **Releases** section on the
> right-hand side of this repository's GitHub page instead.
>
> Builds are currently **unsigned**, so your OS shows a one-time "unknown developer"
> warning — the steps below tell you how to get past it. This is normal for indie
> open-source apps.

### Windows

1. Download **[Maknassa-Setup.exe](https://github.com/LibGdxEngine/Maknassa/releases/latest/download/Maknassa-Setup.exe)**.
2. Double-click it. If Windows shows a blue **"Windows protected your PC"** box, click
   **More info → Run anyway**.
3. Follow the installer, then launch **Maknassa** from the Start menu.

### macOS

1. Download **[Maknassa.dmg](https://github.com/LibGdxEngine/Maknassa/releases/latest/download/Maknassa.dmg)**.
2. Open it and drag **Maknassa** into **Applications**.
3. The first time, **right-click the app → Open** (not double-click), then click
   **Open** in the dialog. macOS remembers this afterward.

### Linux

1. Download **[Maknassa.AppImage](https://github.com/LibGdxEngine/Maknassa/releases/latest/download/Maknassa.AppImage)**.
2. Make it executable: right-click → *Properties → Permissions → Allow executing*, or
   run `chmod +x Maknassa.AppImage`.
3. Double-click it (or run `./Maknassa.AppImage`).

> **Ubuntu 22.04+ note:** If the AppImage does not launch, install FUSE first:
> `sudo apt install libfuse2`. (Sandbox restrictions on Ubuntu 24.04+ are handled
> automatically — the app detects it is running from an AppImage.)

Everything is bundled — there is nothing else to install.

---

## Using it (first run)

1. Open Maknassa. In the sidebar, click **Connect to Facebook** — a real browser
   window opens. Log in to Facebook there, then return to Maknassa. You only do this
   once; the session is saved on your device.
2. Paste a **Facebook post URL** and click **Fetch reactors**.
3. Tick the people you want, then **Block selected**. Blocks are human-paced with a
   random delay, and there's an optional stop-after-N safety brake in the sidebar.

---

## How it works

Two interfaces sit over one shared Python core:

- **Desktop app** — an Electron shell that spawns the Python backend and renders the
  React UI. This is what the installers ship.
- **CLI** (`maknassa`) — `login`, `scrape`, `block`, `unblock`, `block-url`,
  `unblock-url`, `inspect` (for power users / scripting).

Because it drives a real, logged-in browser session, the work stays on your machine:
there is no server, and your Facebook session/cookies are never uploaded anywhere.
Maknassa makes **no** network calls of its own beyond talking to Facebook in your
browser.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Electron main process  (Node.js)                        │
│  index.ts                                                │
│    · spawns maknassa-backend on 127.0.0.1                │
│    · reads stdout PORT/TOKEN handshake                   │
│    · creates BrowserWindow; wires IPC                    │
│    · kills backend on app quit                           │
└────────────────────┬─────────────────────────────────────┘
                     │  IPC (contextBridge)
                     ▼
┌──────────────────────────────────────────────────────────┐
│  Electron renderer  (Bundled Chromium, local files only) │
│  React + TypeScript + Tailwind CSS                       │
│    · window.maknassa.{apiBase, token, openExternal}      │
│    · typed HTTP client -> /api/*                         │
│    · profile links open in the OS browser (openExternal) │
└────────────────────┬─────────────────────────────────────┘
                     │  loopback HTTP  127.0.0.1:<port>
                     │  X-Maknassa-Token: <token>
                     ▼
┌──────────────────────────────────────────────────────────┐
│  maknassa-backend  (FastAPI sidecar, Python)             │
│  reactions/backend.py + reactions/api.py                 │
│    · token-gated /api/* (401 without header)             │
│    · single concurrent browser job (409 busy)            │
│    · jobs: POST -> 202 {job_id}; GET /api/jobs/{id}      │
│    · watchdog: exits ~5s after parent pid disappears     │
└────────────────────┬─────────────────────────────────────┘
                     │  in-process call (same Python process)
                     ▼
┌──────────────────────────────────────────────────────────┐
│  reactions/ core  (shared Python library)                │
│    · browser.py       Playwright sync + stealth          │
│    · service.py       block/unblock functional core      │
│    · blocker.py       DB-driven orchestration            │
│    · extractor.py / storage.py / models.py               │
│         │                                                │
│         ▼  Playwright (sync API)                         │
│  persistent Chromium profile  ────  SQLite               │
└──────────────────────────────────────────────────────────┘
```

Also available: the **CLI** (`reactions/cli.py`) talks to the reactions core directly
in-process, sharing the same persistent profile and SQLite store.

### Startup handshake

When the Electron main process launches, it spawns `maknassa-backend` and reads
exactly two lines from its stdout before opening the window:

```
MAKNASSA_BACKEND_PORT=<port>
MAKNASSA_BACKEND_TOKEN=<token>
```

The port is OS-assigned (unless pinned via `MAKNASSA_BACKEND_PORT`), and the token is
a per-launch `secrets.token_hex(16)` (unless pinned via `MAKNASSA_BACKEND_TOKEN`).
Both lines are printed and flushed *before* uvicorn starts serving, so Electron can
start polling `/api/health` immediately. The token is passed to the renderer via
`contextBridge` and injected as `X-Maknassa-Token` on every request; it is never
written to disk or accessible to web content.

### Single-browser-job rule

The reactions core drives one persistent Chromium profile (the user's Facebook login).
Two concurrent sessions would corrupt that profile directory, so the job manager
admits exactly one running browser job at a time. A second `POST /api/fetch` (or
`/api/block`, `/api/login`) while one is running returns `409 {"error": "busy"}`.

---

## Two Chromiums? How the rendering and the automation differ

Maknassa ships **two separate Chromium binaries** with very different roles. This
question comes up often enough that it deserves a plain answer.

### Chromium #1: Electron's renderer (the UI)

Electron is essentially a Node.js runtime with a pinned Chromium build compiled in.
When you launch Maknassa, Electron uses that bundled Chromium to render the React UI —
the sidebar, the reactor grid, the settings panel. The Electron main process is Node;
the renderer is Chromium; together they form the app window.

Key points:

- **It is not a launchable browser.** Electron's Chromium is statically linked and
  configured specifically to host local HTML/JS — it cannot be launched as a
  standalone browser binary.
- **It only loads local content.** The renderer's source is a bundle of local files
  packaged with the app. It never navigates to remote URLs. External links (e.g. a
  reactor's Facebook profile) are opened in the user's own OS browser via
  `shell.openExternal`, not inside Electron.
- **No Facebook session here.** The renderer authenticates to the local FastAPI
  backend with a per-launch token. It has no direct access to Facebook at all.

### Chromium #2: Playwright's automation browser (the Facebook work)

The Python backend ships a separate Playwright Chromium binary — a real, standard
Chrome/Chromium build that Playwright can launch and drive programmatically. This one:

- **Is a standalone browser binary.** Playwright can start it, navigate it, inject
  scripts, listen to network events — the full Playwright API.
- **Holds the Facebook login session.** It runs in a persistent profile directory
  (`~/.local/share/Maknassa/profiles/…` on Linux, etc.) so the user stays logged in
  across app restarts. The stealth plugin prevents bot-detection fingerprints.
- **Is completely separate from the Electron renderer.** It lives in a different
  directory (`packaging/ms-playwright/` frozen into the backend resource), runs as a
  child process of the Python backend, and Playwright can only talk to it — not to
  Electron's embedded Chromium.

### Why they cannot be merged

You might wonder: "can the Electron renderer just navigate to Facebook directly?"
No — that would expose your Facebook session to the entire renderer process and bypass
the stealth measures. The current split gives a clean boundary: the UI is local and
token-authenticated; the real-browser work is isolated to the Python sidecar.

You might also wonder: "can Playwright drive Electron's Chromium instead of its own?"
Electron's Chromium is not a launchable binary on a known path the way the Playwright
install is. You can use Playwright's Electron driver against the app window itself (we
do in e2e smoke tests), but you cannot use it as a substitute for the logged-in
persistent-profile automation browser.

**Bottom line:** two Chromiums, two jobs — neither can do the other's work.

---

## Data & configuration

All mutable state lives under a **per-user data directory** (never inside the app
bundle), resolved by `reactions/paths.py` via `platformdirs`:

| Item             | Location (default)                          |
| ---------------- | ------------------------------------------- |
| SQLite store     | `<data>/data/reactions.db`                  |
| Browser profiles | `<data>/profiles/<account>/`                |
| UI state (JSON)  | `<data>/ui_state.json`                      |

Where `<data>` is the OS convention:

| OS      | `<data>`                                  |
| ------- | ----------------------------------------- |
| Linux   | `~/.local/share/Maknassa`                 |
| macOS   | `~/Library/Application Support/Maknassa`  |
| Windows | `%LOCALAPPDATA%\Maknassa`                 |

### Environment variables

| Variable                   | Effect                                                                          |
| -------------------------- | ------------------------------------------------------------------------------- |
| `MAKNASSA_DATA_DIR`        | Relocate **all** data under one folder (portable install / tests).              |
| `MAKNASSA_BACKEND_CMD`     | Override the backend binary in dev: e.g. `"../.venv/bin/python -m reactions.backend"`. |
| `MAKNASSA_BACKEND_PORT`    | Pin the backend port instead of choosing a free one.                            |
| `MAKNASSA_BACKEND_TOKEN`   | Pin the backend auth token (useful for integration tests).                      |
| `PLAYWRIGHT_BROWSERS_PATH` | Set automatically by the frozen app to the bundled Chromium.                    |

CLI `--db-path` / `--profile-dir` override the defaults per command; with no flag
they fall back to the per-user locations above.

---

## Run from source (development)

### 1. Python backend

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

python main.py login    # one-time: sign in to Facebook in the opened browser
```

To start the backend on its own (useful when iterating on the API):

```bash
python -m reactions.backend
# Prints: MAKNASSA_BACKEND_PORT=<n>  MAKNASSA_BACKEND_TOKEN=<t>
# Then serves at 127.0.0.1:<n>
```

### 2. Electron frontend (separate terminal)

```bash
cd app
npm install
MAKNASSA_BACKEND_CMD="../.venv/bin/python -m reactions.backend" npm run dev
```

`MAKNASSA_BACKEND_CMD` is shell-split by the Electron main process and spawned
directly — the relative path `../.venv/bin/python` is resolved from the `app/`
directory where Electron starts, so the above form works when your terminal is at the
repo root. If you run from elsewhere, use an absolute path.

For fast UI iteration without a real backend:

```bash
cd app
MAKNASSA_BACKEND_CMD="node scripts/fake-backend.mjs" npm run dev
```

### CLI examples

```bash
python main.py scrape  "https://www.facebook.com/.../posts/..."
python main.py block   "https://www.facebook.com/.../posts/..." --reaction angry
python main.py block   "https://www.facebook.com/.../posts/..." --reaction angry --execute
python main.py block-url "https://www.facebook.com/someone" --execute
```

`block`/`unblock` are **dry-run by default**; pass `--execute` to act. A randomized
delay between actions keeps things human-paced; `--daily-cap N` (0 = unlimited) is a
safety brake.

---

## Building the installers

Each platform produces a single double-click installer with **Chromium bundled**, so
end users need no separate `playwright install`.

The pipeline has two stages:

1. **PyInstaller** freezes `reactions/backend.py` (the FastAPI sidecar + its bundled
   Playwright Chromium) into `dist/maknassa-backend/`.
2. **electron-builder** packages the Electron app and embeds the frozen backend via
   `extraResources`.

```bash
bash packaging/build.sh                                        # Linux -> dist/Maknassa.AppImage
                                                               # macOS -> dist/electron/mac*/Maknassa.app
bash packaging/macos/build_dmg.sh                             # macOS -> dist/Maknassa.dmg (after build.sh)
powershell -ExecutionPolicy Bypass -File packaging\build.ps1   # Windows -> dist\Maknassa-Setup.exe
```

The spec used is `packaging/backend.spec` (not the old `maknassa.spec`). On macOS,
Chromium cannot be frozen directly by PyInstaller (ad-hoc re-signing rejects its nested
`.app` binary), so `build_dmg.sh` injects it after electron-builder and then deep-signs
the whole `.app`.

`build/`, `dist/`, and `packaging/ms-playwright/` are git-ignored.

---

## Publishing a release

Installers are built on GitHub's cloud runners and attached to a GitHub Release by the
[`release-installers`](.github/workflows/release-installers.yml) workflow — native
installers can't be cross-compiled, so each OS builds its own (`windows-latest`,
`macos-latest`, `ubuntu-latest`). The macOS build runs on Apple Silicon (arm64); the
resulting `.dmg` is native on Apple-Silicon Macs — Intel Macs would need a separate
`macos-13` build (GitHub's Intel runners are currently backlogged).

Each runner sets up both Python 3.11 and Node 20, runs the relevant build script, then
attaches the artifact. Two ways to trigger it:

```bash
# Cut a brand-new release: push a tag and the workflow builds + attaches all three.
git tag v1.1.0 && git push origin v1.1.0

# Or attach installers to an EXISTING release (e.g. add Windows/macOS to v1.0.0):
gh workflow run release-installers.yml -f tag=v1.0.0
gh run watch        # follow progress; assets appear on the release when it finishes
```

The workflow keeps the exact filenames `Maknassa-Setup.exe`, `Maknassa.dmg`, and
`Maknassa.AppImage` so the [Download & install](#download--install) links resolve.
Builds are **unsigned** — the download steps above cover the one-time OS warning.

---

## Project layout

```
main.py                     CLI entry shim -> reactions.cli:main
pyproject.toml              packaging metadata, entry points, mypy/ruff config
LICENSE                     MIT licence
DISCLAIMER.md               acceptable-use / no-warranty notice
reactions/
  cli.py                    argparse subcommands
  api.py                    FastAPI app (create_app); all /api/* routes
  backend.py                backend entrypoint: handshake + uvicorn launcher
  paths.py                  per-user data locations (platformdirs)
  browser.py                Playwright scraper + persistent_page + login_flow
  service.py                by-URL block/unblock functional core + FacebookBlocker
  blocker.py                DB-driven orchestration (dry-run, cap, delays)
  ui_fetch.py               fetch_reactors + in_thread helper
  extractor.py  selectors.py  storage.py  models.py  config.py  _js.py
app/
  src/main/                 Electron main process (Node.js)
    backend.ts              spawns + manages the Python backend child process
    index.ts                BrowserWindow, IPC handlers
  src/preload/              contextBridge (window.maknassa)
  src/renderer/             React app (Vite + Tailwind CSS)
    src/lib/api.ts          typed HTTP client + JobPoller
  scripts/fake-backend.mjs  dev stub that emits the PORT/TOKEN handshake
  electron-builder config   embedded in package.json (extraResources: backend/)
packaging/
  backend.spec              PyInstaller one-folder spec (backend only; no Streamlit)
  build.sh / build.ps1      build wrappers (install Chromium + freeze + electron-builder)
  macos/build_dmg.sh        inject Chromium, deep-sign, hdiutil
  windows/maknassa.iss      (legacy Inno Setup — superseded by electron-builder NSIS)
  linux/build_appimage.sh   (legacy — superseded by electron-builder AppImage)
tests/                      pytest suite (fully mocked; conftest isolates data dir)
```

---

## Tests, types & lint

```bash
pytest            # unit tests (all mocked; no real browser/network)
mypy reactions/   # type check (clean)
ruff check .      # lint (clean)
```

In the `app/` directory:

```bash
npm run typecheck   # TypeScript check
npx vitest run      # renderer unit tests (API client, selection store)
```

Tests run in seconds with no external dependencies. `tests/conftest.py` points
`MAKNASSA_DATA_DIR` at a throwaway temp dir so the suite never touches a real data dir.

---

## Contributing

Contributions are welcome — MIT license, issues and pull requests accepted.

**Dev quickstart:** follow [Run from source](#run-from-source-development) above.

**Code layout:**

- `reactions/` — Python core (scraping, blocking, storage, config)
- `reactions/api.py` + `reactions/backend.py` — FastAPI sidecar and its entrypoint
- `app/` — Electron shell (main, preload, React renderer)
- `packaging/` — build scripts and PyInstaller spec
- `tests/` — pytest suite (mock everything; no real browser or network)

**Before opening a PR:** keep `pytest`, `mypy reactions/`, `ruff check .`, and
`npm run typecheck` green, and match the existing style (typed Python, small pure
seams, tests for new logic). By contributing you agree your work is licensed under
the project's [MIT License](LICENSE).

---

## Roadmap

Done: per-user data dirs, Electron desktop shell with React UI, FastAPI sidecar,
in-app Facebook login, free/open-source release with one-click installers, and a
release-installers CI workflow that builds and attaches the Windows/macOS/Linux
installers on GitHub's cloud runners.

> **History note:** early versions used a Streamlit web UI in a pywebview/Playwright
> Chromium native window (`maknassa-gui`). That frontend was replaced by the current
> Electron app (v1.x+).

Deferred follow-ups:

- **Code-signing & notarization** — Windows Authenticode, macOS Developer ID (removes
  the unsigned-app warning).
- **Auto-update** — version check + download/replace flow.
- **Multi-account profiles** — make profile/session a first-class per-account object.
- **Download landing page** — a simple GitHub Pages site with per-OS buttons.
