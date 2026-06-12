// Safe wrappers around the optional preload-bridge UX hooks (OS notification +
// taskbar progress). The bridge is always present in the packaged desktop app, so
// these are normally a thin pass-through; the optional-chaining guard only matters
// to a renderer loaded WITHOUT the preload (a future test/storybook harness), where
// an unguarded call would throw. The data-path bridge methods (getBackendInfo,
// openExternal) stay direct — the app cannot function without them anyway.

export function notify(title: string, body: string): void {
  window.maknassa?.notify?.({ title, body })
}

// 0..1 fills the taskbar/dock progress bar; a negative value clears it.
export function setTaskbarProgress(fraction: number): void {
  window.maknassa?.setProgress?.(fraction)
}
