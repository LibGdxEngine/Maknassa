# Maknassa

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

### 🪟 Windows

1. Download **[Maknassa-Setup.exe](https://github.com/LibGdxEngine/Maknassa/releases/latest/download/Maknassa-Setup.exe)**.
2. Double-click it. If Windows shows a blue **"Windows protected your PC"** box, click
   **More info → Run anyway**.
3. Follow the installer, then launch **Maknassa** from the Start menu.

### 🍎 macOS

1. Download **[Maknassa.dmg](https://github.com/LibGdxEngine/Maknassa/releases/latest/download/Maknassa.dmg)**.
2. Open it and drag **Maknassa** into **Applications**.
3. The first time, **right-click the app → Open** (not double-click), then click
   **Open** in the dialog. macOS remembers this afterward.

### 🐧 Linux

1. Download **[Maknassa.AppImage](https://github.com/LibGdxEngine/Maknassa/releases/latest/download/Maknassa.AppImage)**.
2. Make it executable: right-click → *Properties → Permissions → Allow executing*, or
   run `chmod +x Maknassa.AppImage`.
3. Double-click it (or run `./Maknassa.AppImage`).

Everything is bundled — there is nothing else to install.

---

## Using it (first run)

1. Open Maknassa. In the sidebar, click **🔑 Connect to Facebook** — a real browser
   window opens. Log in to Facebook there, then return to Maknassa. You only do this
   once; the session is saved on your device.
2. Paste a **Facebook post URL** and click **Fetch reactors**.
3. Tick the people you want, then **Block selected**. Blocks are human-paced with a
   random delay, and there's an optional stop-after-N safety brake in the sidebar.

---

## How it works

Two front-ends sit over one shared core:

- **Desktop app** (`maknassa-gui`) — the Streamlit UI in a native window (what the
  installers ship).
- **CLI** (`maknassa`) — `login`, `scrape`, `block`, `unblock`, `block-url`,
  `unblock-url`, `inspect` (for power users / scripting).

Because it drives a real, logged-in browser session, the work stays on your machine:
there is no server, and your Facebook session/cookies are never uploaded anywhere.
Maknassa makes **no** network calls of its own beyond talking to Facebook in your
browser.

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
  thread and a PyInstaller-frozen build can re-exec itself), waits for it to come up,
  then opens it in a `pywebview` window. Closing the window stops the server.
- **Streamlit UI** (`streamlit_app.py`): the in-window UI. The one-time Facebook login
  and each fetch/block run Playwright's sync API on a worker thread
  (`reactions/ui_fetch.in_thread`) so it never collides with Streamlit's event loop.
- **Core** (`reactions/`): the scraping/blocking logic. Pure seams (`collect_records`,
  `select_targets`, the `matches_any` predicates, `build_fetch_query`) are unit-tested
  without a browser; the effectful browser work goes through one stealthed,
  persistent-profile Chromium context (`reactions/browser.persistent_page`).

---

## Data & configuration

All mutable state lives under a **per-user data directory** (never inside the app
bundle), resolved by `reactions/paths.py` via `platformdirs`:

| Item             | Location (default)                          |
| ---------------- | ------------------------------------------- |
| SQLite store     | `<data>/data/reactions.db`                  |
| Browser profiles | `<data>/profiles/<account>/`                |

Where `<data>` is the OS convention:

| OS      | `<data>`                                  |
| ------- | ----------------------------------------- |
| Linux   | `~/.local/share/Maknassa`                 |
| macOS   | `~/Library/Application Support/Maknassa`  |
| Windows | `%LOCALAPPDATA%\Maknassa`                 |

### Environment variables

| Variable                   | Effect                                                                 |
| -------------------------- | ---------------------------------------------------------------------- |
| `MAKNASSA_DATA_DIR`        | Relocate **all** data under one folder (portable install / tests).     |
| `MAKNASSA_NO_WINDOW=1`     | Desktop launcher serves the UI only and prints the URL (no GUI window). |
| `MAKNASSA_GUI_PORT`        | Pin the desktop server port instead of choosing a free one.            |
| `PLAYWRIGHT_BROWSERS_PATH` | Set automatically by the frozen app to the bundled Chromium.           |

CLI `--db-path` / `--profile-dir` override the defaults per command; with no flag
they fall back to the per-user locations above.

---

## Run from source (development)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

python main.py login           # one-time: sign in to Facebook in the opened browser
python -m reactions.desktop    # launch the desktop UI in a window
# …or run the UI directly (then use the in-app "Connect to Facebook" button):
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
delay between actions keeps things human-paced; `--daily-cap N` (0 = unlimited) is a
safety brake.

---

## Building the installers

Each platform produces a single double-click installer with **Chromium bundled**, so
end users need no separate `playwright install`.

```bash
bash packaging/build.sh                                        # Linux/macOS bundle
powershell -ExecutionPolicy Bypass -File packaging\build.ps1   # Windows bundle
```

`build.sh` / `build.ps1` install Chromium into `packaging/ms-playwright`, then run
PyInstaller (`packaging/maknassa.spec`) to produce `dist/maknassa/`. The per-OS
packaging step then wraps that folder into the distributable installer
(`Maknassa-Setup.exe` via Inno Setup, `Maknassa.dmg`, `Maknassa.AppImage`). See
[Publishing a release](#publishing-a-release) for the exact per-OS commands.

> **First build per platform:** Streamlit is lazy-import-heavy. The spec already
> `collect_all`s the known packages; if the *first* build on a new OS hits a
> `ModuleNotFoundError` at runtime, add that module to `hiddenimports` in
> [`packaging/maknassa.spec`](packaging/maknassa.spec). This is the one expected
> manual step of a Streamlit freeze.

The installer is large (~310 MB AppImage) — mostly the bundled Chromium and the
Playwright driver. Streamlit's unused dataframe/chart stack (pandas/pyarrow/altair) is
excluded from the freeze to keep it down. `build/`, `dist/`, and
`packaging/ms-playwright/` are git-ignored.

---

## Publishing a release

There is no CI; releases are built and published by hand. On each target OS, build the
bundle and package its installer, then attach the files to a GitHub Release:

```bash
# Linux
bash packaging/build.sh && bash packaging/linux/build_appimage.sh   # -> dist/Maknassa.AppImage

# macOS
bash packaging/build.sh && bash packaging/macos/build_dmg.sh        # -> dist/Maknassa.dmg

# Windows (PowerShell; needs Inno Setup, i.e. `iscc` on PATH)
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
iscc packaging\windows\maknassa.iss                                 # -> dist\Maknassa-Setup.exe
```

Then create a release on GitHub (e.g. tag `v1.0.0`) and upload the three files, keeping
the exact names `Maknassa-Setup.exe`, `Maknassa.dmg`, and `Maknassa.AppImage` so the
[Download & install](#download--install) links resolve. Builds are **unsigned** — those
same steps cover the one-time OS warning for users.

---

## Project layout

```
main.py                     CLI entry shim -> reactions.cli:main
streamlit_app.py            Streamlit UI (also bundled into the desktop app)
pyproject.toml              packaging metadata, entry points, mypy/ruff config
LICENSE                     MIT licence
DISCLAIMER.md               acceptable-use / no-warranty notice
reactions/
  cli.py                    argparse subcommands
  desktop.py                pywebview + child-process Streamlit launcher (maknassa-gui)
  paths.py                  per-user data locations (platformdirs)
  browser.py                Playwright scraper + persistent_page + login_flow
  service.py                by-URL block/unblock functional core + FacebookBlocker
  blocker.py                DB-driven orchestration (dry-run, cap, delays)
  extractor.py selectors.py storage.py models.py ui_fetch.py config.py _js.py
packaging/
  maknassa.spec             PyInstaller one-folder spec
  build.sh / build.ps1      build wrappers (install Chromium + freeze)
  windows/maknassa.iss      Inno Setup installer script
  linux/build_appimage.sh   macos/build_dmg.sh    per-OS installer packaging
tests/                      pytest suite (fully mocked; conftest isolates data dir)
```

---

## Tests, types & lint

```bash
pytest          # unit tests (all mocked; no real browser/network)
mypy reactions/ # type check (clean)
ruff check .    # lint (clean)
```

Tests run in seconds with no external dependencies. `tests/conftest.py` points
`MAKNASSA_DATA_DIR` at a throwaway temp dir so the suite never touches a real data dir.

---

## Contributing

Issues and pull requests are welcome. Please keep `pytest`, `mypy reactions/`, and
`ruff check .` green, and match the existing style (typed, small pure seams, tests for
new logic). By contributing you agree your work is licensed under the project's
[MIT License](LICENSE).

---

## Roadmap

Done: per-user data dirs, desktop shell, in-app Facebook login, free/open-source
release with one-click installers (built and published manually).

Deferred follow-ups:

- **Code-signing & notarization** — Windows Authenticode, macOS Developer ID (removes
  the unsigned-app warning).
- **Release CI** — a workflow to rebuild/publish installers on a tag (removed for now).
- **Auto-update** — version check + download/replace flow.
- **Multi-account profiles** — make profile/session a first-class per-account object.
- **Download landing page** — a simple GitHub Pages site with per-OS buttons.
