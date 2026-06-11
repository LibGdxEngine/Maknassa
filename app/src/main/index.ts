import { app, BrowserWindow, ipcMain, shell } from 'electron'
import path from 'path'
import { spawnBackend, stopBackend } from './backend'
import type { BackendHandshake } from './backend'
import { is } from '@electron-toolkit/utils'

// Electron's setuid sandbox helper cannot work from an AppImage (squashfs mounts
// nosuid) and Ubuntu 24.04+ also blocks the unprivileged-userns fallback, so a
// double-clicked AppImage would die at startup. The renderer only ever loads our
// local bundle and the localhost API — never remote content — so dropping the
// sandbox in the AppImage case is an acceptable trade for "it just works".
if (process.platform === 'linux' && process.env.APPIMAGE) {
  app.commandLine.appendSwitch('no-sandbox')
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

  win.webContents.on('will-navigate', (event, url) => {
    const appUrl = is.dev ? 'http://localhost:5173' : `file://`
    if (!url.startsWith(appUrl)) {
      event.preventDefault()
      if (url.startsWith('https://') || url.startsWith('http://')) {
        shell.openExternal(url)
      }
    }
  })

  win.on('ready-to-show', () => win.show())

  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    win.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    win.loadFile(path.join(__dirname, '../renderer/index.html'))
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
