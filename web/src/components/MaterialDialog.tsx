import { useEffect, useMemo, useState } from 'react'
import { createFilament, getProfileDetail, updateFilament } from '../api'
import { PLATE_TEMP_KEYS } from '../bedTypes'

// Material types the form offers (the slicer's own filament_type strings).
const MATERIAL_TYPES = [
  'PLA', 'PLA-CF', 'PETG', 'PETG-CF', 'ABS', 'ASA', 'PC', 'PA', 'PA-CF', 'PET', 'PET-CF', 'TPU', 'PVA', 'HIPS', 'PP', 'PPS', 'PEEK', 'Other',
]

interface MaterialDialogProps {
  // create: a new material copied from `base`; edit: change the user's own material `base`.
  mode: 'create' | 'edit'
  base: { vendor: string; name: string }
  onClose: () => void
  onSaved: (name: string) => void
}

type Draft = Record<string, string>

const NUMBER_FIELDS: { key: string; label: string; step: string }[] = [
  { key: 'nozzle_temperature', label: 'Nozzle', step: '1' },
  { key: 'nozzle_temperature_initial_layer', label: 'First layer', step: '1' },
  { key: 'nozzle_temperature_range_low', label: 'Lowest', step: '1' },
  { key: 'nozzle_temperature_range_high', label: 'Highest', step: '1' },
  { key: 'filament_flow_ratio', label: 'Flow ratio', step: '0.01' },
  { key: 'filament_max_volumetric_speed', label: 'Max speed (mm³/s)', step: '0.5' },
  { key: 'filament_density', label: 'Density (g/cm³)', step: '0.01' },
  { key: 'filament_diameter', label: 'Diameter (mm)', step: '0.05' },
  { key: 'fan_min_speed', label: 'Fan min %', step: '1' },
  { key: 'fan_max_speed', label: 'Fan max %', step: '1' },
]

// A preset stores each value as a list of strings (one per extruder variant); the form shows the first.
function first(data: Record<string, unknown>, key: string): string {
  const v = data[key]
  const x = Array.isArray(v) ? v[0] : v
  return typeof x === 'string' || typeof x === 'number' ? String(x) : ''
}

// "409 A material called …" -> the message alone.
function message(err: Error): string {
  return err.message.replace(/^\d{3}\s+/, '')
}

/**
 * The "New material" / "Edit material" form: a copy of an existing material
 * with the dozen settings people change. Everything not shown is inherited
 * from the base, so the result behaves exactly like it. Saved under "My
 * profiles" and offered for every printer.
 */
export default function MaterialDialog({ mode, base, onClose, onSaved }: MaterialDialogProps) {
  const [draft, setDraft] = useState<Draft | null>(null)
  const [plates, setPlates] = useState<{ key: string; label: string }[]>([])
  const [name, setName] = useState(mode === 'edit' ? base.name : `${base.name} (custom)`)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    getProfileDetail(base.vendor, 'filament', base.name)
      .then((detail) => {
        if (cancelled) return
        const d = detail.data
        const next: Draft = { filament_type: first(d, 'filament_type') || 'PLA', filament_vendor: first(d, 'filament_vendor') }
        for (const f of NUMBER_FIELDS) next[f.key] = first(d, f.key)
        const offered: { key: string; label: string }[] = []
        for (const [key, label] of PLATE_TEMP_KEYS) {
          // The four common plates are always offered; the rarer two only when the base mentions them.
          const common = ['textured_plate_temp', 'cool_plate_temp', 'eng_plate_temp', 'hot_plate_temp'].includes(key)
          if (common || d[key] !== undefined) {
            next[key] = first(d, key) || '0'
            offered.push({ key, label: label.replace(' Plate', '') })
          }
        }
        setPlates(offered)
        setDraft(next)
      })
      .catch((err: Error) => !cancelled && setLoadError(message(err)))
    return () => {
      cancelled = true
    }
  }, [base.vendor, base.name])

  const types = useMemo(() => {
    const current = draft?.filament_type
    return current && !MATERIAL_TYPES.includes(current) ? [current, ...MATERIAL_TYPES] : MATERIAL_TYPES
  }, [draft?.filament_type])

  const set = (key: string, value: string) => setDraft((prev) => (prev ? { ...prev, [key]: value } : prev))

  const save = () => {
    if (!draft) return
    const num = (key: string, label: string): number => {
      const n = Number(draft[key])
      if (draft[key] === '' || !Number.isFinite(n)) throw new Error(`${label} must be a number`)
      return n
    }
    let form
    try {
      const cleanName = name.trim()
      if (!cleanName) throw new Error('Give the material a name')
      form = {
        name: cleanName,
        base_name: mode === 'create' ? base.name : undefined,
        filament_type: draft.filament_type,
        filament_vendor: draft.filament_vendor.trim(),
        nozzle_temperature: num('nozzle_temperature', 'Nozzle temperature'),
        nozzle_temperature_initial_layer: num('nozzle_temperature_initial_layer', 'First layer temperature'),
        nozzle_temperature_range_low: num('nozzle_temperature_range_low', 'Lowest temperature'),
        nozzle_temperature_range_high: num('nozzle_temperature_range_high', 'Highest temperature'),
        filament_flow_ratio: num('filament_flow_ratio', 'Flow ratio'),
        filament_max_volumetric_speed: num('filament_max_volumetric_speed', 'Max speed'),
        filament_density: num('filament_density', 'Density'),
        filament_diameter: num('filament_diameter', 'Diameter'),
        fan_min_speed: num('fan_min_speed', 'Fan min'),
        fan_max_speed: num('fan_max_speed', 'Fan max'),
        plate_temps: Object.fromEntries(plates.map((p) => [p.key, num(p.key, `${p.label} bed temperature`)])),
      }
    } catch (err) {
      setError((err as Error).message)
      return
    }
    setSaving(true)
    setError(null)
    ;(mode === 'create' ? createFilament(form) : updateFilament(form))
      .then((saved) => onSaved(saved.name))
      .catch((err: Error) => {
        setError(message(err))
        setSaving(false)
      })
  }

  return (
    <div className="object-picker" role="dialog" aria-modal="true" aria-label={mode === 'create' ? 'New material' : 'Edit material'}>
      <div className="object-picker-header">
        <strong>{mode === 'create' ? 'New material' : 'Edit material'}</strong>
        <button type="button" className="link-button" onClick={onClose}>
          Close ✕
        </button>
      </div>
      <div className="object-picker-scroll material-form">
        {loadError && <p className="banner-error">{loadError}</p>}
        {!draft && !loadError && <p className="auth-hint">Loading…</p>}
        {draft && (
          <>
            <p className="profile-import-help">
              {mode === 'create' ? (
                <>
                  A copy of <strong>{base.name}</strong> with the settings below changed. Everything else is inherited from it.
                  It is saved under <strong>My profiles</strong> and is available for every printer.
                </>
              ) : (
                <>
                  Based on the same material as before; settings not shown here stay as they are.
                </>
              )}
            </p>
            <label>
              Name
              <input type="text" value={name} readOnly={mode === 'edit'} maxLength={120} onChange={(e) => setName(e.target.value)} />
            </label>
            <div className="material-grid">
              <label>
                Type
                <select value={draft.filament_type} onChange={(e) => set('filament_type', e.target.value)}>
                  {types.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Brand
                <input type="text" value={draft.filament_vendor} maxLength={60} onChange={(e) => set('filament_vendor', e.target.value)} />
              </label>
            </div>

            <h3 className="material-section">Temperatures (°C)</h3>
            <div className="material-grid material-grid-4">
              {NUMBER_FIELDS.slice(0, 4).map((f) => (
                <label key={f.key}>
                  {f.label}
                  <input type="number" step={f.step} value={draft[f.key]} onChange={(e) => set(f.key, e.target.value)} />
                </label>
              ))}
            </div>

            <h3 className="material-section">Bed temperature by plate (°C)</h3>
            <div className="material-grid material-grid-3">
              {plates.map((p) => (
                <label key={p.key}>
                  {p.label}
                  <input type="number" step="1" value={draft[p.key]} onChange={(e) => set(p.key, e.target.value)} />
                </label>
              ))}
            </div>
            <p className="auth-hint">0 means this plate isn&rsquo;t offered for this material.</p>

            <h3 className="material-section">Flow and cooling</h3>
            <div className="material-grid material-grid-3">
              {NUMBER_FIELDS.slice(4).map((f) => (
                <label key={f.key}>
                  {f.label}
                  <input type="number" step={f.step} value={draft[f.key]} onChange={(e) => set(f.key, e.target.value)} />
                </label>
              ))}
            </div>
          </>
        )}
        {error && <p className="banner-error">{error}</p>}
        <div className="material-actions">
          <button type="button" className="preview-button" onClick={onClose}>
            Cancel
          </button>
          <button type="button" onClick={save} disabled={!draft || saving}>
            {saving ? 'Saving…' : 'Save material'}
          </button>
        </div>
      </div>
    </div>
  )
}
