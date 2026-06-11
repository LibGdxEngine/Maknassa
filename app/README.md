# Maknassa Desktop App

Electron app with React + TypeScript + Tailwind CSS v4.

## Development

### Prerequisites
- Node.js 20+
- npm 11+

### Setup
```bash
cd app
npm install
```

### Dev with fake backend
```bash
cd app
MAKNASSA_BACKEND_CMD="node scripts/fake-backend.mjs" npm run dev
```

### Type check
```bash
npm run typecheck
```

### Build
```bash
npm run build
```

### Distribution builds
```bash
npm run dist           # current platform
npm run dist:linux     # Linux AppImage
```

## Architecture

- `src/main/` — Electron main process (Node.js)
  - `backend.ts` — spawns and manages the Python backend child process
  - `index.ts` — creates BrowserWindow, wires IPC handlers
- `src/preload/` — preload script (contextBridge)
- `src/renderer/` — React app (Vite)
  - `src/lib/api.ts` — typed HTTP client + JobPoller

## Backend handshake

The backend prints two lines to stdout on startup:
```
MAKNASSA_BACKEND_PORT=<port>
MAKNASSA_BACKEND_TOKEN=<token>
```
The main process parses these before creating the window.

## Packaging notes

### AppImage on Ubuntu 22.04+
AppImage requires FUSE. On systems without FUSE, run with:
```bash
./Maknassa.AppImage --no-sandbox
```
Or install libfuse2: `sudo apt install libfuse2`

### Ubuntu 24.04+ sandbox note
Chrome sandbox on Ubuntu 24.04 requires either `--no-sandbox` flag or unprivileged user namespaces.
electron-builder AppImage target includes `--no-sandbox` by default when FUSE is unavailable.
