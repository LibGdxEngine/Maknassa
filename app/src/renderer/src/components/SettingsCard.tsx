// Sidebar settings card: profile dir, headless toggle, min/max delay, stop-after-N.
// Edits flow up through onUpdate (debounce-saved by useSettings); a subtle tick shows
// when the last save landed.

import type { SaveState } from '../hooks/useSettings'
import type { Settings } from '../lib/types'

interface SettingsCardProps {
  settings: Settings | null
  saveState: SaveState
  onUpdate: (patch: Partial<Settings>) => void
}

export function SettingsCard({ settings, saveState, onUpdate }: SettingsCardProps) {
  return (
    <section className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Settings</h2>
        <SaveTick state={saveState} />
      </div>

      {settings === null ? (
        <p className="text-xs text-slate-500">Loading settings…</p>
      ) : (
        <div className="space-y-4">
          <Field label="Profile dir" hint="Where your logged-in browser session is stored.">
            <input
              type="text"
              value={settings.profile_dir}
              onChange={(e) => onUpdate({ profile_dir: e.target.value })}
              className="w-full rounded-lg border border-white/10 bg-slate-900/60 px-2.5 py-1.5 text-xs text-slate-100 outline-none focus:border-sky-500"
            />
          </Field>

          <label className="flex cursor-pointer items-center justify-between text-xs text-slate-200">
            <span>
              Headless browser
              <span className="ml-1 text-slate-500">(off to watch / solve checkpoints)</span>
            </span>
            <input
              type="checkbox"
              checked={settings.headless}
              onChange={(e) => onUpdate({ headless: e.target.checked })}
              className="h-4 w-4 accent-sky-500"
            />
          </label>

          <Field
            label="Seconds between blocks"
            hint="Random pause keeps blocking human-paced. Lower is faster but riskier."
          >
            <div className="flex items-center gap-2">
              <NumberInput
                value={settings.min_delay}
                min={0}
                step={0.5}
                onCommit={(v) => onUpdate({ min_delay: v })}
                ariaLabel="Minimum delay"
              />
              <span className="text-slate-500">to</span>
              <NumberInput
                value={settings.max_delay}
                min={0}
                step={0.5}
                onCommit={(v) => onUpdate({ max_delay: v })}
                ariaLabel="Maximum delay"
              />
            </div>
          </Field>

          <Field label="Stop after N blocks" hint="Safety brake. 0 = unlimited.">
            <NumberInput
              value={settings.stop_after}
              min={0}
              step={10}
              onCommit={(v) => onUpdate({ stop_after: Math.round(v) })}
              ariaLabel="Stop after N blocks"
            />
          </Field>
        </div>
      )}
    </section>
  )
}

function SaveTick({ state }: { state: SaveState }) {
  if (state === 'saving') return <span className="text-xs text-slate-500">Saving…</span>
  if (state === 'saved') return <span className="text-xs text-emerald-400">✓ Saved</span>
  if (state === 'error') return <span className="text-xs text-red-400">Save failed</span>
  return null
}

function Field({
  label,
  hint,
  children
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1">
      <div className="text-xs font-medium text-slate-300">{label}</div>
      {children}
      {hint && <p className="text-[11px] leading-snug text-slate-500">{hint}</p>}
    </div>
  )
}

function NumberInput({
  value,
  min,
  step,
  onCommit,
  ariaLabel
}: {
  value: number
  min: number
  step: number
  onCommit: (value: number) => void
  ariaLabel: string
}) {
  return (
    <input
      type="number"
      aria-label={ariaLabel}
      value={value}
      min={min}
      step={step}
      onChange={(e) => {
        const parsed = Number(e.target.value)
        if (!Number.isNaN(parsed)) onCommit(parsed)
      }}
      className="w-20 rounded-lg border border-white/10 bg-slate-900/60 px-2.5 py-1.5 text-xs text-slate-100 outline-none focus:border-sky-500"
    />
  )
}
