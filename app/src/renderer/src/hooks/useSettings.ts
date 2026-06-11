// Settings state: loads from GET /api/settings on mount, then debounce-saves changes
// via PUT. Exposes a transient 'saved' flag so the panel can flash a subtle tick.

import { useCallback, useEffect, useRef, useState } from 'react'
import { get, put } from '../lib/api'
import type { Settings } from '../lib/types'

export type SaveState = 'idle' | 'saving' | 'saved' | 'error'

export interface SettingsApi {
  settings: Settings | null
  saveState: SaveState
  update: (patch: Partial<Settings>) => void
}

const SAVE_DEBOUNCE_MS = 600
const SAVED_FLASH_MS = 1500

export function useSettings(enabled: boolean, onError?: (err: Error) => void): SettingsApi {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError

  // Load only once the API client is configured (App flips `enabled` after the
  // first successful health poll) — fetching on mount would race getBackendInfo().
  useEffect(() => {
    if (!enabled || settings !== null) return
    let cancelled = false
    get<Settings>('/api/settings')
      .then((loaded) => {
        if (!cancelled) setSettings(loaded)
      })
      .catch((err: Error) => {
        if (!cancelled) onErrorRef.current?.(err)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled])

  useEffect(() => {
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current)
      if (flashTimer.current) clearTimeout(flashTimer.current)
    }
  }, [])

  const update = useCallback((patch: Partial<Settings>) => {
    setSettings((prev) => {
      if (prev === null) return prev
      const next = { ...prev, ...patch }
      if (saveTimer.current) clearTimeout(saveTimer.current)
      saveTimer.current = setTimeout(() => {
        setSaveState('saving')
        put<Settings>('/api/settings', patch)
          .then((saved) => {
            setSettings(saved)
            setSaveState('saved')
            if (flashTimer.current) clearTimeout(flashTimer.current)
            flashTimer.current = setTimeout(() => setSaveState('idle'), SAVED_FLASH_MS)
          })
          .catch((err: Error) => {
            setSaveState('error')
            onErrorRef.current?.(err)
          })
      }, SAVE_DEBOUNCE_MS)
      return next
    })
  }, [])

  return { settings, saveState, update }
}
