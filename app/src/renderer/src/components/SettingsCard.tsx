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
    <section className="rounded-[10px] border border-[rgba(255,255,255,0.06)] bg-[#131926] p-4 shadow-[0_1px_3px_rgba(0,0,0,0.4),0_4px_12px_rgba(0,0,0,0.25)]">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#4e5d73]">Settings</h2>
        <SaveTick state={saveState} />
      </div>

      {settings === null ? (
        <div className="space-y-2">
          {[40, 24, 32, 24].map((w, i) => (
            <div
              key={i}
              className="skeleton-pulse h-6 rounded-md bg-[#1a2235]"
              style={{ width: `${w * 2.5}px` }}
            />
          ))}
        </div>
      ) : (
        <div className="space-y-4">
          <Field label="Profile dir" hint="Where your logged-in browser session is stored.">
            <input
              type="text"
              value={settings.profile_dir}
              onChange={(e) => onUpdate({ profile_dir: e.target.value })}
              className="w-full rounded-[6px] border border-[rgba(255,255,255,0.08)] bg-[#1a2235] px-2.5 py-1.5 text-[11px] font-mono text-[#9aa5b8] outline-none transition focus:border-[rgba(59,130,246,0.5)] focus:ring-1 focus:ring-[rgba(59,130,246,0.2)]"
            />
          </Field>

          <label className="flex cursor-pointer items-center justify-between gap-3 text-[11px] text-[#9aa5b8]">
            <span className="leading-snug">
              Headless browser
              <span className="block text-[10px] text-[#4e5d73]">Off to watch / solve checkpoints</span>
            </span>
            <div className="relative shrink-0">
              <input
                type="checkbox"
                checked={settings.headless}
                onChange={(e) => onUpdate({ headless: e.target.checked })}
                className="mk-check h-4 w-4 rounded accent-[#3b82f6]"
                aria-label="Headless browser"
              />
            </div>
          </label>

          <Field
            label="Delay between blocks"
            hint="Random pause keeps blocking human-paced."
          >
            <div className="flex items-center gap-2">
              <NumberInput
                value={settings.min_delay}
                min={0}
                step={0.5}
                onCommit={(v) => onUpdate({ min_delay: v })}
                ariaLabel="Minimum delay"
              />
              <span className="text-[11px] text-[#4e5d73]">–</span>
              <NumberInput
                value={settings.max_delay}
                min={0}
                step={0.5}
                onCommit={(v) => onUpdate({ max_delay: v })}
                ariaLabel="Maximum delay"
              />
              <span className="text-[10px] text-[#4e5d73]">sec</span>
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
  if (state === 'saving') return <span className="text-[10px] text-[#4e5d73]">Saving…</span>
  if (state === 'saved') return <span className="text-[10px] text-[#34d399]">✓ Saved</span>
  if (state === 'error') return <span className="text-[10px] text-[#f87171]">Save failed</span>
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
    <div className="space-y-1.5">
      <div className="text-[11px] font-medium text-[#9aa5b8]">{label}</div>
      {children}
      {hint && <p className="text-[10px] leading-snug text-[#4e5d73]">{hint}</p>}
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
      className="w-16 rounded-[6px] border border-[rgba(255,255,255,0.08)] bg-[#1a2235] px-2 py-1.5 text-center text-[11px] font-mono text-[#e8edf5] outline-none transition focus:border-[rgba(59,130,246,0.5)] focus:ring-1 focus:ring-[rgba(59,130,246,0.2)]"
    />
  )
}
