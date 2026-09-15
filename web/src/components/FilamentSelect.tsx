import { useMemo, useState } from 'react'
import type { ProfileSummary } from '../types'

interface FilamentSelectProps {
  profiles: ProfileSummary[]
  vendor: string
  filamentName: string
  onFilamentChange: (name: string) => void
}

// Split out of PrinterSelect.tsx: material/filament choice is something you
// reasonably want to change on its own (swap PLA for PETG) without having
// to dig into "Printer settings" (vendor/printer/process), which auto-
// collapses once a saved printer is picked -- this lives in "Quick
// settings" instead, which is exactly where a per-job tweak like this
// belongs.
export default function FilamentSelect({ profiles, vendor, filamentName, onFilamentChange }: FilamentSelectProps) {
  const [filamentQuery, setFilamentQuery] = useState('')

  const filaments = useMemo(() => {
    const inVendor = profiles.filter((p) => p.vendor === vendor && p.kind === 'filament')
    // Not every printer vendor bundles its own filament profiles -- Voron,
    // Creality's DIY-oriented lines, and other community/OEM-machine-only
    // vendors have machine/process profiles but zero filament ones of
    // their own. Falling back to the full catalog (rather than leaving the
    // list permanently empty) is what keeps material selection -- and by
    // extension saving a printer or slicing at all -- possible for those.
    const pool = inVendor.length > 0 ? inVendor : profiles.filter((p) => p.kind === 'filament')
    const q = filamentQuery.trim().toLowerCase()
    const matches = q ? pool.filter((p) => p.name.toLowerCase().includes(q)) : pool
    const sorted = matches.sort((a, b) => a.name.localeCompare(b.name)).slice(0, 200)

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

  return (
    <div className="field-group">
      <label>
        Material
        <input
          type="text"
          placeholder={`Search ${filaments.length ? '' : 'materials'}…`}
          value={filamentQuery}
          onChange={(e) => setFilamentQuery(e.target.value)}
        />
        <select value={filamentName} size={6} onChange={(e) => onFilamentChange(e.target.value)}>
          {filaments.map((f) => (
            <option key={f.name} value={f.name}>
              {f.name}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
