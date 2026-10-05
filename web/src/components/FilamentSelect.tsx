import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { ProfileSummary } from '../types'

// Where the user's own (imported or created) profiles live; they are offered for every printer.
const IMPORTED_VENDOR = 'My profiles'

interface FilamentSelectProps {
  profiles: ProfileSummary[]
  vendor: string
  filamentName: string
  onFilamentChange: (name: string) => void
  // Overridable so App.tsx can label multiple instances "Slot 1 material",
  // "Slot 2 material", etc. for multi-extruder/AMS printers.
  label?: string
  // Rendered inline next to the label text (App.tsx uses this for each
  // slot's color swatch). Deliberately inline with the label rather than
  // beside the whole component: the search input + multi-row <select>
  // below can be much taller than the swatch, and vertically aligning a
  // short sibling against that tall block (confirmed via a mobile
  // screenshot) leaves it looking like it floats disconnected, off to one
  // side, between slots -- anchoring it to the label keeps it visually
  // tied to the slot it actually belongs to at any width.
  accessory?: ReactNode
  // A full-width row rendered below the label (App.tsx uses this for a
  // row of one-click preset color swatches) -- kept separate from
  // `accessory` since cramming several swatches into the same inline row
  // as the label text would either overflow or force an awkward wrap on
  // narrow screens.
  belowLabel?: ReactNode
  // "+ New material from …" and, for the user's own materials, Edit / Delete.
  onNewMaterial?: (base: ProfileSummary) => void
  onEditMaterial?: (material: ProfileSummary) => void
  onDeleteMaterial?: (material: ProfileSummary) => void
}

// Split out of PrinterSelect.tsx: material/filament choice is something you
// reasonably want to change on its own (swap PLA for PETG) without having
// to dig into "Printer settings" (vendor/printer/process), which auto-
// collapses once a saved printer is picked -- this lives in the "Material"
// section instead, which is exactly where a per-job tweak like this
// belongs.
export default function FilamentSelect({
  profiles,
  vendor,
  filamentName,
  onFilamentChange,
  label = 'Material',
  accessory,
  belowLabel,
  onNewMaterial,
  onEditMaterial,
  onDeleteMaterial,
}: FilamentSelectProps) {
  const [filamentQuery, setFilamentQuery] = useState('')
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  const filaments = useMemo(() => {
    const inVendor = profiles.filter((p) => p.vendor === vendor && p.kind === 'filament')
    // Not every printer vendor bundles its own filament profiles -- Voron,
    // Creality's DIY-oriented lines, and other community/OEM-machine-only
    // vendors have machine/process profiles but zero filament ones of
    // their own. Falling back to the full catalog (rather than leaving the
    // list permanently empty) is what keeps material selection -- and by
    // extension saving a printer or slicing at all -- possible for those.
    // The user's own materials are offered whichever printer is chosen.
    const mine = profiles.filter((p) => p.vendor === IMPORTED_VENDOR && p.kind === 'filament')
    const pool =
      inVendor.length > 0
        ? [...inVendor, ...mine.filter((m) => !inVendor.some((p) => p.name === m.name))]
        : profiles.filter((p) => p.kind === 'filament')
    const q = filamentQuery.trim().toLowerCase()
    const matches = q ? pool.filter((p) => p.name.toLowerCase().includes(q)) : pool
    const byName = (a: ProfileSummary, b: ProfileSummary) => a.name.localeCompare(b.name)
    // The user's own materials come first so a search window of 200 never cuts them off.
    const sorted = [
      ...matches.filter((p) => p.vendor === IMPORTED_VENDOR).sort(byName),
      ...matches.filter((p) => p.vendor !== IMPORTED_VENDOR).sort(byName),
    ].slice(0, 200)

    // The current selection can easily fall outside this search/200-item
    // window (confirmed: an auto-picked fallback default alphabetically
    // past the cutoff) -- a plain HTML <select> silently displays its
    // first rendered <option> whenever its `value` doesn't match any of
    // them, which would show something other than what's actually
    // selected. Always keep the true selection visible/selectable so the
    // dropdown never lies about what's picked.
    if (filamentName && !sorted.some((p) => p.name === filamentName)) {
      const current = profiles.find((p) => p.kind === 'filament' && p.name === filamentName)
      if (current) sorted.unshift(current)
    }
    return sorted
  }, [profiles, vendor, filamentQuery, filamentName])

  const selected = profiles.find((p) => p.kind === 'filament' && p.name === filamentName)
  const selectedIsMine = selected?.vendor === IMPORTED_VENDOR
  const mineInList = filaments.filter((p) => p.vendor === IMPORTED_VENDOR)

  return (
    <div className="field-group">
      <label>
        <span className="filament-select-label-row">
          <span>{label}</span>
          {accessory}
        </span>
        {belowLabel}
        <input
          type="text"
          placeholder={`Search ${filaments.length ? '' : 'materials'}…`}
          value={filamentQuery}
          onChange={(e) => setFilamentQuery(e.target.value)}
        />
        <select
          value={filamentName}
          size={6}
          onChange={(e) => {
            setConfirmingDelete(false)
            onFilamentChange(e.target.value)
          }}
        >
          {mineInList.length > 0 ? (
            <>
              <optgroup label="My materials">
                {mineInList.map((f) => (
                  <option key={f.name} value={f.name}>
                    {f.name}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Built in">
                {filaments
                  .filter((p) => p.vendor !== IMPORTED_VENDOR)
                  .map((f) => (
                    <option key={f.name} value={f.name}>
                      {f.name}
                    </option>
                  ))}
              </optgroup>
            </>
          ) : (
            filaments.map((f) => (
              <option key={f.name} value={f.name}>
                {f.name}
              </option>
            ))
          )}
        </select>
      </label>
      {selected && onNewMaterial && (
        <div className="material-links">
          <button type="button" className="link-button" onClick={() => onNewMaterial(selected)}>
            + New material from &ldquo;{selected.name}&rdquo;&hellip;
          </button>
          {selectedIsMine && onEditMaterial && (
            <button type="button" className="link-button" onClick={() => onEditMaterial(selected)}>
              Edit
            </button>
          )}
          {selectedIsMine &&
            onDeleteMaterial &&
            (confirmingDelete ? (
              <span>
                Delete this material?{' '}
                <button
                  type="button"
                  className="link-button danger-text"
                  onClick={() => {
                    setConfirmingDelete(false)
                    onDeleteMaterial(selected)
                  }}
                >
                  Yes, delete
                </button>{' '}
                <button type="button" className="link-button" onClick={() => setConfirmingDelete(false)}>
                  Keep
                </button>
              </span>
            ) : (
              <button type="button" className="link-button danger-text" onClick={() => setConfirmingDelete(true)}>
                Delete
              </button>
            ))}
        </div>
      )}
    </div>
  )
}
