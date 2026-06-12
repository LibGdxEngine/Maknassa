/// <reference types="vite/client" />

interface MaknassaBridge {
  getBackendInfo(): Promise<{ apiBase: string; token: string; version: string }>
  openExternal(url: string): Promise<void>
  notify(payload: { title: string; body: string }): Promise<void>
  setProgress(fraction: number): Promise<void>
}

declare interface Window {
  maknassa: MaknassaBridge
}
