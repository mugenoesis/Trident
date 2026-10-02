import { useEffect, useRef, useState } from 'react'
import { deleteImportedProfile, importProfiles, listImportedProfiles } from '../api'
import type { ImportedProfile, ImportResult } from '../types'

interface ProfileImportDialogProps {
  onClose: () => void
  // Called after anything was imported or deleted, so the profile dropdowns
  // can reload.
  onChanged: () => void
}

const KIND_LABEL: Record<string, string> = { machine: 'Printer', filament: 'Material', process: 'Process' }
const KIND_HEADING: Record<string, string> = { machine: 'Printers', filament: 'Materials', process: 'Process profiles' }
// What OrcaSlicer's own Import Configs accepts.
const ACCEPT = '.json,.zip,.orca_printer,.orca_filament,.orca_bundle'

// Opened from the "Import profiles…" link next to the printer vendor
// dropdown: pick files (single presets or bundles), see what happened, and
// manage (delete) what was imported earlier.
export default function ProfileImportDialog({ onClose, onChanged }: ProfileImportDialogProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [imported, setImported] = useState<ImportedProfile[]>([])
  const [lastFiles, setLastFiles] = useState<File[]>([])
  const [result, setResult] = useState<ImportResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reload = () =>
    listImportedProfiles()
      .then(setImported)
      .catch((err: Error) => setError(err.message))

  useEffect(() => {
    let live = true
    listImportedProfiles()
      .then((list) => live && setImported(list))
      .catch((err: Error) => live && setError(err.message))
    return () => {
      live = false
    }
  }, [])

  const run = (files: File[], overwrite: boolean) => {
    setBusy(true)
    setError(null)
    importProfiles(files, overwrite)
      .then((res) => {
        setResult(res)
        if (res.imported.length > 0) onChanged()
        return reload()
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setBusy(false))
  }

  const handleFiles = (list: FileList | null) => {
    const files = list ? [...list] : []
    if (files.length === 0) return
    setLastFiles(files)
    run(files, false)
  }

  const handleDelete = (p: ImportedProfile) => {
    deleteImportedProfile(p.kind, p.name)
      .then(() => {
        onChanged()
        return reload()
      })
      .catch((err: Error) => setError(err.message))
  }

  const kinds = ['machine', 'filament', 'process']

  return (
    <div className="object-picker" role="dialog" aria-modal="true" aria-label="Import profiles">
      <div className="object-picker-header">
        <strong>Import profiles</strong>
        <button type="button" className="link-button" onClick={onClose}>
          Close ✕
        </button>
      </div>

      <div className="object-picker-scroll">
        <p className="profile-import-help">
          Choose printer, material or process profiles exported from OrcaSlicer: <code>.json</code> files or{' '}
          <code>.zip</code> / <code>.orca_printer</code> / <code>.orca_filament</code> / <code>.orca_bundle</code>{' '}
          bundles. They appear under the vendor <strong>My profiles</strong> and are only visible to you.
        </p>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => {
            handleFiles(e.target.files)
            e.target.value = ''
          }}
        />
        <div>
          <button type="button" className="object-picker-done" disabled={busy} onClick={() => inputRef.current?.click()}>
            {busy ? 'Importing…' : 'Choose files…'}
          </button>
        </div>

        {error && <p className="field-error">{error}</p>}

        {result && (
          <div className="profile-import-result" role="status">
            {result.imported.map((p) => (
              <div className="profile-import-row" key={`i-${p.kind}-${p.name}`}>
                <span className="profile-import-tag">{KIND_LABEL[p.kind] ?? p.kind}</span>
                <span>{p.name}</span>
                <span className="profile-import-ok">imported</span>
                {p.warning && <span className="profile-import-note">{p.warning}</span>}
              </div>
            ))}
            {result.conflicts.length > 0 && (
              <div className="profile-import-conflicts">
                <p>
                  {result.conflicts.length === 1 ? '1 profile was' : `${result.conflicts.length} profiles were`} already
                  imported and not replaced: {result.conflicts.map((c) => c.name).join(', ')}.
                </p>
                <button type="button" className="object-picker-secondary" disabled={busy} onClick={() => run(lastFiles, true)}>
                  Overwrite
                </button>
              </div>
            )}
            {result.skipped.map((s, i) => (
              <div className="profile-import-row" key={`s-${i}`}>
                <span className="profile-import-tag">skipped</span>
                <span>{s.name ?? s.file}</span>
                <span className="profile-import-note">{s.reason}</span>
              </div>
            ))}
          </div>
        )}

        <h4 className="profile-import-heading">Your imported profiles</h4>
        {imported.length === 0 && <p className="profile-import-help">Nothing imported yet.</p>}
        {kinds.map((kind) => {
          const rows = imported.filter((p) => p.kind === kind)
          if (rows.length === 0) return null
          return (
            <div key={kind}>
              <div className="profile-import-kind">{KIND_HEADING[kind]}</div>
              {rows.map((p) => (
                <div className="profile-import-row" key={`${p.kind}-${p.name}`}>
                  <span>
                    {p.name}
                    {p.inherits && <span className="profile-import-note"> based on {p.inherits}</span>}
                  </span>
                  <button type="button" className="link-button" onClick={() => handleDelete(p)}>
                    Delete
                  </button>
                </div>
              ))}
            </div>
          )
        })}
      </div>

      <div className="object-picker-footer">
        <span className="object-picker-count" />
        <button type="button" className="object-picker-done" onClick={onClose}>
          Done
        </button>
      </div>
    </div>
  )
}
