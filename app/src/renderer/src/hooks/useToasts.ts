// Tiny toast system: top-right, dismissible, auto-expiring. Used for fetch/job
// failures, the 409 busy case, and backend-unreachable notices.

import { useCallback, useEffect, useRef, useState } from 'react'

export type ToastKind = 'info' | 'success' | 'warning' | 'error'

export interface Toast {
  id: number
  kind: ToastKind
  message: string
}

export interface ToastApi {
  toasts: Toast[]
  push: (kind: ToastKind, message: string) => number
  dismiss: (id: number) => void
}

const DEFAULT_TTL_MS = 6000

export function useToasts(ttlMs = DEFAULT_TTL_MS): ToastApi {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map())

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
  }, [])

  const push = useCallback(
    (kind: ToastKind, message: string): number => {
      const id = nextId.current++
      setToasts((prev) => [...prev, { id, kind, message }])
      const timer = setTimeout(() => dismiss(id), ttlMs)
      timers.current.set(id, timer)
      return id
    },
    [dismiss, ttlMs]
  )

  useEffect(() => {
    const active = timers.current
    return () => {
      for (const timer of active.values()) clearTimeout(timer)
      active.clear()
    }
  }, [])

  return { toasts, push, dismiss }
}
