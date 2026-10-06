import { useEffect, useState } from 'react'
import { exportProfiles, listImportedProfiles } from '../api'
import type { ExportItem, ImportedProfile } from '../types'

interface ExportDialogProps {
  onClose: () => void
}

const KIND_LABEL: Record<string, string> = { machine: 'printer', filament: 'material', process: 'process' }

/**
 * Download your own printers, materials and process settings as a file desktop OrcaSlicer opens
 * (.orca_printer for one printer, .orca_filament for one material, .orca_bundle otherwise).
 */
export default function ExportDialog({ onClose }: ExportDialogProps) {
  const [items, setItems] = useState<ImportedProfile[] | null>(null)
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const keyOf = (p: { kind: string; name: string }) => `${p.kind}:${p.name}`

  useEffect(() => {
    listImportedProfiles()
      .then((list) => {
        setItems(list)
        setChosen(new Set(list.map(keyOf)))
      })
      .catch((err: Error) => setError(err.message))
  }, [])

  const toggle = (key: string) =>
    setChosen((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  const download = () => {
    if (!items) return
    const picked: ExportItem[] = items.filter((p) => chosen.has(keyOf(p))).map((p) => ({ kind: p.kind as ExportItem['kind'], name: p.name }))
    setBusy(true)
    setError(null)
    exportProfiles(picked)
      .then(({ blob, filename }) => {
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = filename
        document.body.appendChild(link)
        link.click()
        link.remove()
        URL.revokeObjectURL(url)
        onClose()
      })
      .catch((err: Error) => {
        setError(err.message.replace(/^\d{3}\s+/, ''))
        setBusy(false)
      })
  }

  return (
    <div className="object-picker" role="dialog" aria-modal="true" aria-label="Export profiles">
      <div className="object-picker-header">
        <strong>Export profiles</strong>
        <button type="button" className="link-button" onClick={onClose}>
          Close ✕
        </button>
      </div>
      <div className="object-picker-scroll material-form">
        <p className="profile-import-help">
          Your own printers, materials and process settings, as a file desktop OrcaSlicer opens (<code>.orca_printer</code>,{' '}
          <code>.orca_filament</code> or <code>.orca_bundle</code>). Settings you inherit are not copied, so the printer or material
          they come from has to exist where you import.
        </p>
        {!items && !error && <p className="auth-hint">Loading…</p>}
        {items && items.length === 0 && <p className="auth-hint">You have no profiles of your own yet. Make a printer or a material, or import some.</p>}
        {items && items.length > 0 && (
          <ul className="advanced-results">
            {items.map((p) => (
              <li key={keyOf(p)}>
                <label className="checkbox-label">
                  <input type="checkbox" checked={chosen.has(keyOf(p))} onChange={() => toggle(keyOf(p))} />
                  <span>
                    {p.name}
                    <small>
                      {KIND_LABEL[p.kind] ?? p.kind}
                      {p.inherits ? ` · based on ${p.inherits}` : ''}
                    </small>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
        {error && <p className="banner-error">{error}</p>}
        <div className="material-actions">
          <button type="button" className="preview-button" onClick={onClose}>
            Cancel
          </button>
          <button type="button" onClick={download} disabled={busy || chosen.size === 0}>
            {busy ? 'Preparing…' : 'Download'}
          </button>
        </div>
      </div>
    </div>
  )
}
