import { app, BrowserWindow, ipcMain, session, shell } from 'electron'
import path from 'path'
import { pathToFileURL } from 'url'
import { spawnBackend, stopBackend } from './backend'
import type { BackendHandshake } from './backend'
import { is } from '@electron-toolkit/utils'

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
  const policy = is.dev
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

function createWindow(hs: BackendHandshake): BrowserWindow {
  const iconPath = path.join(
    process.resourcesPath,
    process.platform === 'win32' ? 'icon.ico' : process.platform === 'darwin' ? 'icon.icns' : 'icon.png'
  )

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
      sandbox: false,
      preload: path.join(__dirname, '../preload/index.js')
    }
  })

  handshake = hs

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
  const allowedPrefix = is.dev && devUrl ? devUrl : RENDERER_INDEX_URL
  win.webContents.on('will-navigate', (event, url) => {
    if (url === allowedPrefix || url.startsWith(allowedPrefix)) return
    event.preventDefault()
    if (url.startsWith('https://') || url.startsWith('http://')) {
      shell.openExternal(url)
    }
  })

  win.on('ready-to-show', () => win.show())

  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
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

app.whenReady().then(async () => {
  installCsp()
  try {
    console.log('[main] spawning backend...')
    const hs = await spawnBackend()
    console.log(`[main] backend ready on port ${hs.port}`)
    createWindow(hs)
  } catch (err) {
    console.error('[main] backend failed:', err)
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
