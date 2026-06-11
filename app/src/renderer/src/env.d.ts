/// <reference types="vite/client" />

interface MaknassaBridge {
  getBackendInfo(): Promise<{ apiBase: string; token: string; version: string }>
  openExternal(url: string): Promise<void>
}

declare interface Window {
  maknassa: MaknassaBridge
}
