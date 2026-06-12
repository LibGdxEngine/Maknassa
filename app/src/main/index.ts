import { app, BrowserWindow, dialog, ipcMain, Notification, session, shell } from 'electron'
import { existsSync } from 'fs'
import path from 'path'
import { pathToFileURL } from 'url'
import { spawnBackend, stopBackend } from './backend'
import type { BackendHandshake } from './backend'

// Electron's setuid sandbox helper cannot work from an AppImage (squashfs mounts
// nosuid) and Ubuntu 24.04+ also blocks the unprivileged-userns fallback, so a
// double-clicked AppImage would die at startup. The renderer's *document* is always
// our local bundle and its only API target is the loopback backend; the sole remote
// content is non-executable reactor avatar <img>s from Facebook's CDN (locked down
// by the CSP below). Dropping the sandbox is an acceptable trade for "it just works".
// AppRun also passes --no-sandbox so this does not depend on the APPIMAGE env var.
if (process.platform === 'linux' && process.env.APPIMAGE) {
  app.commandLine.appendSwitch('no-sandbox')
}

// The production renderer's document URL (file://…/renderer/index.html); used both
// to load the window and as the only same-document navigation target we allow.
const RENDERER_INDEX_URL = pathToFileURL(
  path.join(__dirname, '../renderer/index.html')
).toString()

// Content-Security-Policy: a defense-in-depth backstop that matters more because the
// renderer runs unsandboxed on Linux. Production locks the document to its own bundle
// (no remote scripts, ever), permits the loopback API for fetch, and allows reactor
// avatars only from Facebook's image CDN (+ data: URIs the offline fake backend uses).
// Dev relaxes script/connect rules so Vite's HMR client works.
function installCsp(): void {
  const policy = !app.isPackaged
    ? "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; " +
      "script-src 'self' 'unsafe-inline' 'unsafe-eval'; connect-src 'self' ws: http://127.0.0.1:* http://localhost:*"
    : "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; " +
      "img-src 'self' data: https://*.fbcdn.net https://*.facebook.com; " +
      "connect-src http://127.0.0.1:*; base-uri 'none'; form-action 'none'"
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [policy]
      }
    })
  })
}

let handshake: BackendHandshake | null = null
// The live window, so the notify/set-progress IPC handlers can reach it.
let mainWindow: BrowserWindow | null = null

function resolveIconPath(): string | undefined {
  const iconFile = process.platform === 'win32'
    ? 'icon.ico'
    : process.platform === 'darwin'
      ? 'icon.icns'
      : 'icon.png'
  const candidate = path.join(process.resourcesPath, iconFile)
  return existsSync(candidate) ? candidate : undefined
}

function createWindow(hs: BackendHandshake): BrowserWindow {
  const iconPath = resolveIconPath()

  const win = new BrowserWindow({
    width: 1280,
    height: 900,
    minWidth: 1000,
    minHeight: 700,
    backgroundColor: '#0b0f17',
    icon: iconPath,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      // Keep Chromium's renderer sandbox on (the default). The preload uses only
      // contextBridge + ipcRenderer, both sandbox-safe, and the renderer is pure
      // web, so nothing needs it off. On the Linux AppImage the --no-sandbox flag
      // (from AppRun) disables it anyway; on macOS/Windows this keeps it enforced.
      sandbox: true,
      preload: path.join(__dirname, '../preload/index.js')
    }
  })

  handshake = hs
  mainWindow = win
  win.on('closed', () => {
    if (mainWindow === win) mainWindow = null
  })

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://') || url.startsWith('http://')) {
      shell.openExternal(url)
    }
    return { action: 'deny' }
  })

  // The UI never navigates the document itself (all in-app routing is React state),
  // so deny every will-navigate except a reload of our own page, and shell out any
  // http(s) target. The allowed prefix is the exact dev server or the bundle's
  // index.html — not a bare `file://`, which would match any local path.
  const devUrl = process.env['ELECTRON_RENDERER_URL']
  const allowedPrefix = !app.isPackaged && devUrl ? devUrl : RENDERER_INDEX_URL
  win.webContents.on('will-navigate', (event, url) => {
    if (url === allowedPrefix || url.startsWith(allowedPrefix)) return
    event.preventDefault()
    if (url.startsWith('https://') || url.startsWith('http://')) {
      shell.openExternal(url)
    }
  })

  win.on('ready-to-show', () => win.show())

  if (!app.isPackaged && process.env['ELECTRON_RENDERER_URL']) {
    win.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    win.loadURL(RENDERER_INDEX_URL)
  }

  return win
}

ipcMain.handle('backend-info', () => {
  if (!handshake) throw new Error('Backend not ready')
  return {
    apiBase: `http://127.0.0.1:${handshake.port}`,
    token: handshake.token,
    version: app.getVersion()
  }
})

ipcMain.handle('open-external', (_event, url: string) => {
  if (typeof url === 'string' && (url.startsWith('https://') || url.startsWith('http://'))) {
    return shell.openExternal(url)
  }
  return Promise.resolve()
})

// Notify only when the window is NOT focused — a notification for something the user
// is already watching is just noise. A long block batch is exactly when they alt-tab.
ipcMain.handle('notify', (_event, payload: { title?: unknown; body?: unknown }) => {
  if (mainWindow?.isFocused()) return
  if (!Notification.isSupported()) return
  const title = typeof payload?.title === 'string' ? payload.title : 'Maknassa'
  const body = typeof payload?.body === 'string' ? payload.body : ''
  new Notification({ title, body }).show()
})

// Taskbar/dock progress. 0..1 fills it; a negative value clears it (setProgressBar(-1)).
ipcMain.handle('set-progress', (_event, fraction: unknown) => {
  if (!mainWindow) return
  const n = typeof fraction === 'number' && Number.isFinite(fraction) ? fraction : -1
  mainWindow.setProgressBar(n < 0 ? -1 : Math.min(1, Math.max(0, n)))
})

app.whenReady().then(async () => {
  installCsp()
  try {
    console.log('[main] spawning backend...')
    const hs = await spawnBackend()
    console.log(`[main] backend ready on port ${hs.port}`)
    createWindow(hs)
  } catch (err) {
    console.error('[main] backend failed:', err)
    const details = err instanceof Error ? (err.stack ?? err.message) : String(err)
    dialog.showErrorBox(
      'Maknassa failed to start',
      `Maknassa could not start its local backend service.\n\n${details}`
    )
    app.quit()
  }
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    stopBackend()
    app.quit()
  }
})

app.on('activate', async () => {
  const { BrowserWindow: BW } = await import('electron')
  if (BW.getAllWindows().length === 0 && handshake) {
    createWindow(handshake)
  }
})
