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
  onExportClick: () => void
  onDeleteImportedPrinter: () => void
  // "+ New printer from …" (a copy of the selected printer, or of nothing in particular), and Edit for your own.
  onNewPrinter: () => void
  onEditPrinter: () => void
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
  onExportClick,
  onDeleteImportedPrinter,
  onNewPrinter,
  onEditPrinter,
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
  // One of your own printers has no processes of its own: offer those of the vendor its chosen process
  // belongs to (the printer it was copied from), plus your own.
  const processVendor =
    vendor === IMPORTED_VENDOR ? (profiles.find((p) => p.kind === 'process' && p.name === processName)?.vendor ?? vendor) : vendor
  const processes = useMemo(
    () =>
      profiles
        .filter((p) => p.kind === 'process' && (p.vendor === processVendor || (vendor === IMPORTED_VENDOR && p.vendor === IMPORTED_VENDOR)))
        .sort((a, b) => a.name.localeCompare(b.name)),
    [profiles, processVendor, vendor],
  )
  return (
    <div className="field-group">
      <div className="profile-import-link-row">
        <button type="button" className="link-button" onClick={onImportClick}>
          Import profiles…
        </button>
        {' · '}
        <button type="button" className="link-button" onClick={onExportClick}>
          Export…
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

      <div className="material-links">
        <button type="button" className="link-button" onClick={onNewPrinter}>
          {printerName ? <>+ New printer from &ldquo;{printerName}&rdquo;&hellip;</> : <>+ New printer&hellip;</>}
        </button>
        {vendor === IMPORTED_VENDOR && printerName && (
          <>
            <button type="button" className="link-button" onClick={onEditPrinter}>
              Edit
            </button>
            <button type="button" className="link-button danger-text" onClick={onDeleteImportedPrinter}>
              Delete
            </button>
          </>
        )}
      </div>

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
