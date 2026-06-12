// App shell: left sidebar (settings + connection) and main content column, mirroring
// the Streamlit layout. Owns cross-cutting state (backend health, session, reactors,
// selection, filters) and wires the thin feature components together. All async job
// logic lives in lib/jobs + lib/api; selection math in lib/selection.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { configureApi, get } from './lib/api'
import { selectedCount as countSelected, selectedUrls as urlsForSelection } from './lib/selection'
import {
  loadBlocklist,
  mergeBlocked,
  removeBlocked,
  saveBlocklist,
  type Blocklist
} from './lib/blocklist'
import type { BlockOutcome, FetchResult, HealthResponse, SessionInfo, UIReactor } from './lib/types'
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
  const [search, setSearch] = useState('')
  // Persistent "already blocked" memory (localStorage), keyed by profile_key.
  const [blocked, setBlocked] = useState<Blocklist>(() => loadBlocklist())
  const [hideBlocked, setHideBlocked] = useState(false)

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
    // A new reactor set always starts unselected and unfiltered — deliberate
    // per-batch consent for the irreversible block.
    setReactors(result.reactors)
    setExpectedTotal(result.expected_total)
    setSelected(new Set())
    setFilters(new Set())
    setSearch('')
    setHideBlocked(false)
  }, [])

  const reactorList = reactors ?? []
  const selCount = countSelected(reactorList, selected)
  const selUrls = urlsForSelection(reactorList, selected)
  const blockedKeys = useMemo(() => new Set(Object.keys(blocked)), [blocked])
  // profile_key AND profile_url -> name, so BlockBar's outcome rows (the by-URL block
  // path returns no name) can show a human label. Built from the whole fetched set.
  const nameLookup = useMemo(() => {
    const m: Record<string, string> = {}
    for (const r of reactorList) {
      if (!r.name) continue
      m[r.profile_key] = r.name
      if (r.profile_url) m[r.profile_url] = r.name
    }
    return m
  }, [reactorList])
  // The block callback can outlive its render by minutes; read the latest names via a
  // ref so re-fetching mid-block doesn't enrich with a stale mapping.
  const nameLookupRef = useRef(nameLookup)
  nameLookupRef.current = nameLookup

  // Record a finished block run into the persistent blocklist. Block outcomes carry no
  // name (by-URL path), so enrich from the grid's known names before storing.
  function handleBlocked(outcomes: BlockOutcome[]): void {
    const now = new Date().toISOString()
    const lookup = nameLookupRef.current
    setBlocked((prev) => {
      const enriched = outcomes.map((o) => ({
        ...o,
        name: o.name ?? lookup[o.profile_key] ?? null
      }))
      const next = mergeBlocked(prev, enriched, now)
      saveBlocklist(next)
      return next
    })
  }

  function handleUnblocked(key: string): void {
    setBlocked((prev) => {
      const next = removeBlocked(prev, key)
      if (next !== prev) saveBlocklist(next)
      return next
    })
  }

  return (
    <div className="h-screen overflow-hidden bg-[#0b0f17] text-[#e8edf5]" style={{ fontFamily: "'DM Sans', 'Geist', ui-sans-serif, system-ui, sans-serif" }}>
      <Toasts toasts={toasts.toasts} onDismiss={toasts.dismiss} />

      <div className="mx-auto flex h-full max-w-[1400px] flex-col lg:flex-row">
        {/* Sidebar */}
        <aside className="flex w-full shrink-0 flex-col overflow-y-auto border-b border-[rgba(255,255,255,0.06)] bg-[#0e1420] p-5 lg:h-full lg:w-[296px] lg:border-b-0 lg:border-r">
          {/* Brand */}
          <header className="mb-5 pb-4 border-b border-[rgba(255,255,255,0.06)]">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] bg-[#1a2235] text-[17px] shadow-sm border border-[rgba(255,255,255,0.09)] leading-none">
                🚫
              </div>
              <h1 className="text-[15px] font-semibold tracking-[-0.02em] text-[#e8edf5]">Maknassa</h1>
            </div>
            <p className="mt-2 text-[11px] leading-relaxed text-[#4e5d73]">
              Fetch a post&apos;s reactors, then block the ones you pick.
            </p>
          </header>

          <div className="space-y-3">
            <ConnectionCard session={session} onSession={setSession} onBusy={showBusy} />
            <SettingsCard
              settings={settings.settings}
              saveState={settings.saveState}
              onUpdate={settings.update}
            />
          </div>

          {/* Backend health footer */}
          <div className="mt-5 pt-4 border-t border-[rgba(255,255,255,0.06)]">
            <div className="flex items-center gap-1.5">
              <span className={`h-1.5 w-1.5 rounded-full ${
                health.kind === 'up' ? 'bg-[#34d399]' :
                health.kind === 'connecting' ? 'bg-[#fbbf24] animate-pulse' :
                'bg-[#f87171]'
              }`} />
              <span className="text-[11px] text-[#4e5d73]">
                {health.kind === 'up' && `Backend v${health.version}`}
                {health.kind === 'connecting' && 'Connecting…'}
                {health.kind === 'down' && <span className="text-[#f87171]">Backend offline</span>}
              </span>
            </div>
          </div>
        </aside>

        {/* Main */}
        <main className="flex flex-1 flex-col overflow-auto p-6 gap-6 lg:h-full">
          <FetchSection
            reactors={reactors}
            expectedTotal={expectedTotal}
            onResult={handleFetchResult}
            onError={showError}
            onBusy={showBusy}
          />

          {reactors === null && (
            <div className="flex flex-1 items-center justify-center">
              <EmptyState />
            </div>
          )}

          {reactors !== null && reactors.length > 0 && (
            <ReactorGrid
              reactors={reactorList}
              selected={selected}
              activeFilters={filters}
              search={search}
              blockedKeys={blockedKeys}
              hideBlocked={hideBlocked}
              selectedCount={selCount}
              onSelectedChange={setSelected}
              onFiltersChange={setFilters}
              onSearchChange={setSearch}
              onToggleHideBlocked={() => setHideBlocked((v) => !v)}
            />
          )}

          {reactors !== null && reactors.length === 0 && (
            <NothingCaptured />
          )}

          <BlockBar
            selectedCount={selCount}
            selectedUrls={selUrls}
            names={nameLookup}
            onBlocked={handleBlocked}
            onUnblocked={handleUnblocked}
            onBusy={showBusy}
            onError={showError}
          />
        </main>
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center text-center">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-[14px] bg-[#131926] border border-[rgba(255,255,255,0.07)] text-[26px] shadow-[0_4px_16px_rgba(0,0,0,0.4)] leading-none">
        🔗
      </div>
      <p className="text-sm font-medium text-[#9aa5b8]">Paste a post URL above to get started</p>
      <p className="mt-1 text-[11px] text-[#4e5d73]">Reactors will appear here after fetching</p>
    </div>
  )
}

function NothingCaptured() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-[#131926] border border-[rgba(255,255,255,0.06)] text-2xl">
        🤷
      </div>
      <p className="text-sm font-medium text-[#9aa5b8]">No reactors captured</p>
      <p className="mt-1 text-[11px] text-[#4e5d73]">Facebook returned an empty reactor list for this post.</p>
    </div>
  )
}
