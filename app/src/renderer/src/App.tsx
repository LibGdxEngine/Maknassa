import { useEffect, useState } from 'react'
import { configureApi, get } from './lib/api'

interface BackendInfo {
  apiBase: string
  token: string
  version: string
}

interface HealthResponse {
  status: string
  version?: string
}

type UIState =
  | { kind: 'loading'; message: string }
  | { kind: 'ok'; appVersion: string; backendVersion: string }
  | { kind: 'error'; message: string }

export default function App() {
  const [state, setState] = useState<UIState>({ kind: 'loading', message: 'Connecting to backend...' })

  useEffect(() => {
    let cancelled = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    async function init() {
      try {
        const info: BackendInfo = await window.maknassa.getBackendInfo()
        configureApi(info.apiBase, info.token)
        poll(info.version)
      } catch (err) {
        if (!cancelled) {
          setState({ kind: 'error', message: `Failed to get backend info: ${String(err)}` })
        }
      }
    }

    async function poll(appVersion: string) {
      if (cancelled) return
      try {
        const health = await get<HealthResponse>('/api/health')
        if (!cancelled) {
          setState({
            kind: 'ok',
            appVersion,
            backendVersion: health.version ?? 'unknown'
          })
        }
      } catch {
        if (!cancelled) {
          setState({ kind: 'loading', message: 'Retrying backend connection...' })
          retryTimer = setTimeout(() => poll(appVersion), 2000)
        }
      }
    }

    init()

    return () => {
      cancelled = true
      if (retryTimer !== null) clearTimeout(retryTimer)
    }
  }, [])

  return (
    <div className="min-h-screen bg-[#0b0f17] text-white flex items-center justify-center">
      <div className="text-center space-y-4">
        <h1 className="text-4xl font-bold text-white">Maknassa</h1>
        {state.kind === 'loading' && (
          <div className="space-y-2">
            <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin mx-auto" />
            <p className="text-gray-400">{state.message}</p>
          </div>
        )}
        {state.kind === 'ok' && (
          <div className="space-y-1">
            <p className="text-green-400 text-xl font-semibold">
              Backend: ok (v{state.backendVersion})
            </p>
            <p className="text-gray-400 text-sm">App version: {state.appVersion}</p>
          </div>
        )}
        {state.kind === 'error' && (
          <p className="text-red-400">{state.message}</p>
        )}
      </div>
    </div>
  )
}
