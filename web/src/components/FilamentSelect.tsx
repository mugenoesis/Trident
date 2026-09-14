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
    const q = filamentQuery.trim().toLowerCase()
    const matches = q ? inVendor.filter((p) => p.name.toLowerCase().includes(q)) : inVendor
    return matches.sort((a, b) => a.name.localeCompare(b.name)).slice(0, 200)
  }, [profiles, vendor, filamentQuery])

  return (
    <div className="field-group">
      <label>
        Material
        <input
          type="text"
          placeholder={vendor ? `Search ${filaments.length ? '' : 'materials'}…` : 'Pick a vendor first'}
          value={filamentQuery}
          disabled={!vendor}
          onChange={(e) => setFilamentQuery(e.target.value)}
        />
        <select
          value={filamentName}
          disabled={!vendor}
          size={6}
          onChange={(e) => onFilamentChange(e.target.value)}
        >
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
