// App shell: left sidebar (settings + connection) and main content column, mirroring
// the Streamlit layout. Owns cross-cutting state (backend health, session, reactors,
// selection, filters) and wires the thin feature components together. All async job
// logic lives in lib/jobs + lib/api; selection math in lib/selection.

import { useCallback, useEffect, useRef, useState } from 'react'
import { configureApi, get } from './lib/api'
import { selectedCount as countSelected, selectedUrls as urlsForSelection } from './lib/selection'
import type { FetchResult, HealthResponse, SessionInfo, UIReactor } from './lib/types'
import { ConnectionCard } from './components/ConnectionCard'
import { SettingsCard } from './components/SettingsCard'
import { FetchSection } from './components/FetchSection'
import { ReactorGrid } from './components/ReactorGrid'
import { BlockBar } from './components/BlockBar'
import { Toasts } from './components/Toasts'
import { useToasts } from './hooks/useToasts'
import { useSettings } from './hooks/useSettings'

type Health =
  | { kind: 'connecting' }
  | { kind: 'up'; version: string }
  | { kind: 'down' }

export default function App() {
  const [health, setHealth] = useState<Health>({ kind: 'connecting' })
  const [ready, setReady] = useState(false)
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [reactors, setReactors] = useState<UIReactor[] | null>(null)
  const [expectedTotal, setExpectedTotal] = useState(0)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [filters, setFilters] = useState<Set<string>>(new Set())

  const toasts = useToasts()
  const pushRef = useRef(toasts.push)
  pushRef.current = toasts.push

  const onSettingsError = useCallback((err: Error) => {
    pushRef.current('error', `Settings: ${err.message}`)
  }, [])
  const settings = useSettings(ready, onSettingsError)

  const showBusy = useCallback(() => {
    pushRef.current('warning', 'Another browser task is running. Wait for it to finish.')
  }, [])
  const showError = useCallback((message: string) => {
    pushRef.current('error', message)
  }, [])

  // Establish the API connection from the preload bridge, then poll /api/health until
  // it answers (retrying with a backend-down notice) and load the session once.
  useEffect(() => {
    let cancelled = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let warnedDown = false

    async function loadSession(): Promise<void> {
      try {
        const info = await get<SessionInfo>('/api/session')
        if (!cancelled) setSession(info)
      } catch {
        // Session load failure is non-fatal; the connection card stays in its default.
      }
    }

    async function poll(): Promise<void> {
      if (cancelled) return
      try {
        const h = await get<HealthResponse>('/api/health')
        if (cancelled) return
        setHealth({ kind: 'up', version: h.version ?? 'unknown' })
        warnedDown = false
        if (!ready) {
          setReady(true)
          await loadSession()
        }
      } catch {
        if (cancelled) return
        setHealth({ kind: 'down' })
        if (!warnedDown) {
          warnedDown = true
          pushRef.current('error', 'Backend is unreachable. Retrying…')
        }
        retryTimer = setTimeout(poll, 2000)
      }
    }

    async function init(): Promise<void> {
      try {
        const backend = await window.maknassa.getBackendInfo()
        configureApi(backend.apiBase, backend.token)
        poll()
      } catch (err) {
        if (!cancelled) {
          setHealth({ kind: 'down' })
          pushRef.current('error', `Failed to reach backend: ${String(err)}`)
        }
      }
    }

    init()
    return () => {
      cancelled = true
      if (retryTimer !== null) clearTimeout(retryTimer)
    }
    // ready is intentionally read once at first success; re-running would re-poll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleFetchResult = useCallback((result: FetchResult) => {
    // A new reactor set always starts unselected and unfiltered (deliberate per-batch
    // consent for the irreversible block) — mirrors streamlit_app's selection reset.
    setReactors(result.reactors)
    setExpectedTotal(result.expected_total)
    setSelected(new Set())
    setFilters(new Set())
  }, [])

  const reactorList = reactors ?? []
  const selCount = countSelected(reactorList, selected)
  const selUrls = urlsForSelection(reactorList, selected)

  return (
    <div className="min-h-screen bg-[#0b0f17] text-slate-100">
      <Toasts toasts={toasts.toasts} onDismiss={toasts.dismiss} />

      <div className="mx-auto flex min-h-screen max-w-[1400px] flex-col lg:flex-row">
        {/* Sidebar */}
        <aside className="w-full shrink-0 space-y-4 border-b border-white/10 bg-[#0d121c] p-5 lg:w-80 lg:border-b-0 lg:border-r">
          <header>
            <h1 className="text-xl font-bold tracking-tight">🚫 Maknassa</h1>
            <p className="mt-1 text-xs text-slate-400">
              Fetch a post&apos;s reactors, then block the ones you pick.
            </p>
          </header>

          <ConnectionCard session={session} onSession={setSession} onBusy={showBusy} />
          <SettingsCard
            settings={settings.settings}
            saveState={settings.saveState}
            onUpdate={settings.update}
          />

          <div className="pt-1 text-[11px] text-slate-600">
            {health.kind === 'up' && <span>Backend ok (v{health.version})</span>}
            {health.kind === 'connecting' && <span>Connecting to backend…</span>}
            {health.kind === 'down' && <span className="text-red-400">Backend offline</span>}
          </div>
        </aside>

        {/* Main */}
        <main className="flex-1 space-y-6 p-6">
          <FetchSection
            reactors={reactors}
            expectedTotal={expectedTotal}
            onResult={handleFetchResult}
            onError={showError}
            onBusy={showBusy}
          />

          {reactors !== null && reactors.length > 0 && (
            <ReactorGrid
              reactors={reactorList}
              selected={selected}
              activeFilters={filters}
              selectedCount={selCount}
              onSelectedChange={setSelected}
              onFiltersChange={setFilters}
            />
          )}

          <BlockBar
            selectedCount={selCount}
            selectedUrls={selUrls}
            onBusy={showBusy}
            onError={showError}
          />
        </main>
      </div>
    </div>
  )
}
