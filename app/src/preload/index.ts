import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('maknassa', {
  getBackendInfo: (): Promise<{ apiBase: string; token: string; version: string }> =>
    ipcRenderer.invoke('backend-info'),
  openExternal: (url: string): Promise<void> => ipcRenderer.invoke('open-external', url)
})
