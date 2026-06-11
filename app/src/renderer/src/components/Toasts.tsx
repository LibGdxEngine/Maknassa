import { useEffect, useState } from 'react'
import type { Toast, ToastKind } from '../hooks/useToasts'

const KIND_CONFIG: Record<ToastKind, { bg: string; border: string; text: string; bar: string; icon: string }> = {
  info:    { bg: 'bg-[#0e1e35]', border: 'border-[rgba(59,130,246,0.3)]', text: 'text-[#93c5fd]', bar: 'bg-[#3b82f6]', icon: 'ℹ' },
  success: { bg: 'bg-[#0b1e17]', border: 'border-[rgba(52,211,153,0.3)]', text: 'text-[#6ee7b7]', bar: 'bg-[#34d399]', icon: '✓' },
  warning: { bg: 'bg-[#1c1607]', border: 'border-[rgba(251,191,36,0.3)]',  text: 'text-[#fde68a]', bar: 'bg-[#fbbf24]', icon: '⚠' },
  error:   { bg: 'bg-[#1e0b0b]', border: 'border-[rgba(248,113,113,0.3)]', text: 'text-[#fca5a5]', bar: 'bg-[#f87171]', icon: '✕' },
}

interface ToastsProps {
  toasts: Toast[]
  onDismiss: (id: number) => void
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const [visible, setVisible] = useState(false)
  const cfg = KIND_CONFIG[toast.kind]

  useEffect(() => {
    // Trigger enter animation on mount
    const t = requestAnimationFrame(() => setVisible(true))
    return () => cancelAnimationFrame(t)
  }, [])

  return (
    <div
      role="alert"
      aria-live="polite"
      className={[
        'relative flex items-start gap-3 overflow-hidden rounded-[10px] border pl-4 pr-3 py-3 text-sm shadow-[0_4px_16px_rgba(0,0,0,0.5)] backdrop-blur-sm',
        cfg.bg,
        cfg.border,
        cfg.text,
        'transition-all duration-200 ease-out',
        visible ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-6',
      ].join(' ')}
    >
      {/* Color-coded left border accent */}
      <div className={`absolute inset-y-0 left-0 w-[3px] rounded-l-[10px] ${cfg.bar}`} />

      {/* Icon */}
      <span className="shrink-0 text-xs font-bold leading-5 opacity-80">{cfg.icon}</span>

      {/* Message */}
      <span className="flex-1 leading-snug text-xs">{toast.message}</span>

      {/* Dismiss */}
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss notification"
        className="shrink-0 rounded opacity-50 transition hover:opacity-100 focus-visible:outline-2 focus-visible:outline-current focus-visible:outline-offset-1"
      >
        <svg className="h-3.5 w-3.5" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
          <path d="M2 2l8 8M10 2l-8 8" />
        </svg>
      </button>
    </div>
  )
}

export function Toasts({ toasts, onDismiss }: ToastsProps) {
  if (toasts.length === 0) return null
  return (
    <div
      className="fixed top-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2"
      aria-label="Notifications"
    >
      {toasts.map((toast) => (
        <ToastItem
          key={toast.id}
          toast={toast}
          onDismiss={() => onDismiss(toast.id)}
        />
      ))}
    </div>
  )
}
