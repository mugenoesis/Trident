import { useMemo } from 'react'
import type { ProfileSummary } from '../types'

interface PrinterSelectProps {
  profiles: ProfileSummary[]
  vendor: string
  printerName: string
  processName: string
  onVendorChange: (vendor: string) => void
  onPrinterChange: (name: string) => void
  onProcessChange: (name: string) => void
  // "Import profiles…" link, and (only when an imported printer is the
  // current one) a delete link -- see ProfileImportDialog.
  onImportClick: () => void
  onDeleteImportedPrinter: () => void
}

// Vendor the importer files user profiles under (api/app/userprofiles.py).
const IMPORTED_VENDOR = 'My profiles'

// Material/filament choice lives in FilamentSelect.tsx now, rendered
// separately under the "Material" section -- see App.tsx.
export default function PrinterSelect({
  profiles,
  vendor,
  printerName,
  processName,
  onVendorChange,
  onPrinterChange,
  onProcessChange,
  onImportClick,
  onDeleteImportedPrinter,
}: PrinterSelectProps) {
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
  return (
    <div className="field-group">
      <div className="profile-import-link-row">
        <button type="button" className="link-button" onClick={onImportClick}>
          Import profiles…
        </button>
      </div>
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

      {vendor === IMPORTED_VENDOR && printerName && (
        <button type="button" className="link-button" onClick={onDeleteImportedPrinter}>
          Delete this imported printer
        </button>
      )}

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
