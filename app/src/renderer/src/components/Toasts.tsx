import type { Toast, ToastKind } from '../hooks/useToasts'

const KIND_STYLES: Record<ToastKind, string> = {
  info: 'border-sky-500/40 bg-sky-500/10 text-sky-200',
  success: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  warning: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
  error: 'border-red-500/40 bg-red-500/10 text-red-200'
}

interface ToastsProps {
  toasts: Toast[]
  onDismiss: (id: number) => void
}

export function Toasts({ toasts, onDismiss }: ToastsProps) {
  if (toasts.length === 0) return null
  return (
    <div className="fixed top-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role="alert"
          className={`flex items-start gap-3 rounded-lg border px-4 py-3 text-sm shadow-lg backdrop-blur ${KIND_STYLES[toast.kind]}`}
        >
          <span className="flex-1 leading-snug">{toast.message}</span>
          <button
            type="button"
            onClick={() => onDismiss(toast.id)}
            aria-label="Dismiss"
            className="shrink-0 rounded text-current/70 transition hover:text-current"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  )
}
