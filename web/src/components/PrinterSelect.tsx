import { useMemo, useState } from 'react'
import type { ProfileSummary } from '../types'

interface PrinterSelectProps {
  profiles: ProfileSummary[]
  vendor: string
  printerName: string
  processName: string
  filamentName: string
  onVendorChange: (vendor: string) => void
  onPrinterChange: (name: string) => void
  onProcessChange: (name: string) => void
  onFilamentChange: (name: string) => void
}

export default function PrinterSelect({
  profiles,
  vendor,
  printerName,
  processName,
  filamentName,
  onVendorChange,
  onPrinterChange,
  onProcessChange,
  onFilamentChange,
}: PrinterSelectProps) {
  const [filamentQuery, setFilamentQuery] = useState('')

  const vendors = useMemo(
    () => [...new Set(profiles.map((p) => p.vendor))].sort(),
    [profiles],
  )
  const printers = useMemo(
    () =>
      profiles.filter((p) => p.vendor === vendor && p.kind === 'machine').sort((a, b) =>
        a.name.localeCompare(b.name),
      ),
    [profiles, vendor],
  )
  const processes = useMemo(
    () =>
      profiles.filter((p) => p.vendor === vendor && p.kind === 'process').sort((a, b) =>
        a.name.localeCompare(b.name),
      ),
    [profiles, vendor],
  )
  const filaments = useMemo(() => {
    const inVendor = profiles.filter((p) => p.vendor === vendor && p.kind === 'filament')
    const q = filamentQuery.trim().toLowerCase()
    const matches = q ? inVendor.filter((p) => p.name.toLowerCase().includes(q)) : inVendor
    return matches.sort((a, b) => a.name.localeCompare(b.name)).slice(0, 200)
  }, [profiles, vendor, filamentQuery])

  return (
    <div className="field-group">
      <label>
        Printer vendor
        <select value={vendor} onChange={(e) => onVendorChange(e.target.value)}>
          <option value="" disabled>
            Select a vendor…
          </option>
          {vendors.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </label>

      <label>
        Printer (nozzle size shown in name)
        <select
          value={printerName}
          disabled={!vendor}
          onChange={(e) => onPrinterChange(e.target.value)}
        >
          <option value="" disabled>
            {vendor ? 'Select a printer…' : 'Pick a vendor first'}
          </option>
          {printers.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name}
            </option>
          ))}
        </select>
      </label>

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

      <details className="advanced-process">
        <summary>Process profile (auto-selected from printer default)</summary>
        <label>
          <select
            value={processName}
            disabled={!vendor}
            onChange={(e) => onProcessChange(e.target.value)}
          >
            {processes.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </details>
    </div>
  )
}
