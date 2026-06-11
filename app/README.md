# Maknassa Desktop App

Electron + electron-vite app with React, TypeScript, and Tailwind CSS v4. This
directory contains the frontend shell only; the Python backend lives in `reactions/`.

## Prerequisites

- Node.js 20+
- npm 11+
- Python 3.11+ with the `reactions` package installed (for real-backend dev mode)

## Setup

```bash
cd app
npm install
```

## Development

### With a real backend (full dev stack)

Start from the repo root with the Python venv active:

```bash
cd app
MAKNASSA_BACKEND_CMD="../.venv/bin/python -m reactions.backend" npm run dev
```

The path `../.venv/bin/python` is relative to `app/` (where Electron starts). The
main process shell-splits `MAKNASSA_BACKEND_CMD` and spawns it directly, so the
above form works when your terminal is at the repo root. Use an absolute path if you
are running from a different directory.

### With the fake backend stub (UI-only)

Iterating on the renderer without a Python environment:

```bash
cd app
MAKNASSA_BACKEND_CMD="node scripts/fake-backend.mjs" npm run dev
```

`fake-backend.mjs` emits the `MAKNASSA_BACKEND_PORT` / `MAKNASSA_BACKEND_TOKEN`
handshake lines and serves minimal stub responses.

## Type checking

```bash
npm run typecheck
```

This runs three separate `tsc --noEmit` passes: `tsconfig.vite.json` (vite config),
`tsconfig.node.json` (Electron main + preload), and `tsconfig.web.json` (renderer).

## Unit tests

```bash
npm test
# or
npx vitest run
```

Vitest runs renderer unit tests under `src/renderer/src/**/*.test.ts` in Node
environment (no jsdom). Tests cover the typed API client (`lib/api.ts`), job polling
logic, and selection store.

## Build (renderer + main bundles)

```bash
npm run build
```

Output goes to `out/`. Required before running electron-builder or the e2e smoke.

## Distribution builds

`electron-builder.yml` at the repo root of `app/` configures targets and embeds the
frozen backend from `../dist/maknassa-backend/` via `extraResources`. Build the
frozen backend first (see [packaging/build.sh](../packaging/build.sh)).

```bash
npm run dist           # current platform (electron-vite build + electron-builder)
npm run dist:linux     # Linux AppImage explicitly
```

Output lands in `../dist/electron/`. The full pipeline (freeze backend + electron-
builder) is wrapped by `packaging/build.sh` (Linux/macOS) and `packaging/build.ps1`
(Windows).

## E2E smoke test

```bash
node scripts/e2e-smoke.mjs [screenshot-path]
```

Uses Playwright's Electron driver to launch the built app (`out/main/index.js`),
waits for the renderer to render and confirm the backend health round-trip, then
saves a screenshot. Exits 0 only when the renderer shows "Backend: ok". Set
`MAKNASSA_DATA_DIR` to a scratch dir to avoid touching real user data.

## Architecture

```
src/main/
  backend.ts      spawns and manages the Python backend child process;
                  reads the stdout PORT/TOKEN handshake with 60s timeout
  index.ts        creates BrowserWindow (1280x900, contextIsolation:true,
                  nodeIntegration:false); wires IPC handlers; quits backend on close
src/preload/
  index.ts        contextBridge: exposes window.maknassa = {apiBase, token,
                  version, openExternal} to the renderer; openExternal routes
                  external URLs (e.g. Facebook profiles) to the OS browser
src/renderer/
  src/lib/api.ts  typed HTTP client; injects X-Maknassa-Token; JobPoller for
                  /api/jobs/{id} long-poll; surfaces 409 busy as a typed error
scripts/
  fake-backend.mjs   dev stub: emits handshake + serves minimal /api/* responses
  e2e-smoke.mjs      Playwright Electron driver smoke test + screenshot
electron-builder.yml electron-builder config: AppImage (Linux), NSIS (Windows),
                     dmg (macOS); embeds ../dist/maknassa-backend/ as extraResources
```

## Backend handshake

The backend prints two lines to stdout on startup, before uvicorn begins serving:

```
MAKNASSA_BACKEND_PORT=<port>
MAKNASSA_BACKEND_TOKEN=<token>
```

`backend.ts` buffers stdout line-by-line and resolves the spawn promise as soon as
both lines arrive. If either line is missing after 60 seconds, the promise rejects
and the app shows an error. The token is passed to the renderer via `contextBridge`
and sent as `X-Maknassa-Token` on every `/api/*` request.

## Packaging notes

### AppImage on Ubuntu 22.04+

AppImage requires FUSE. If the AppImage does not launch, install it:

```bash
sudo apt install libfuse2
```

### Ubuntu 24.04+ sandbox note

Electron's setuid sandbox helper cannot work from an AppImage (squashfs mounts are
nosuid) and Ubuntu 24.04+ also blocks the unprivileged-userns fallback, so
`src/main/index.ts` appends `--no-sandbox` automatically whenever the `APPIMAGE`
env var is present. The renderer only ever loads the local bundle and the
localhost API, never remote content, which is what makes that trade acceptable.
