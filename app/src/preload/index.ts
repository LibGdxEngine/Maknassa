import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('maknassa', {
  getBackendInfo: (): Promise<{ apiBase: string; token: string; version: string }> =>
    ipcRenderer.invoke('backend-info'),
  openExternal: (url: string): Promise<void> => ipcRenderer.invoke('open-external', url),
  // Fire an OS notification (the main process suppresses it when the window is
  // focused) — used to flag the end of a long, human-paced block batch or fetch.
  notify: (payload: { title: string; body: string }): Promise<void> =>
    ipcRenderer.invoke('notify', payload),
  // Drive the taskbar/dock progress bar. 0..1 fills it; a negative value clears it.
  setProgress: (fraction: number): Promise<void> => ipcRenderer.invoke('set-progress', fraction)
})
