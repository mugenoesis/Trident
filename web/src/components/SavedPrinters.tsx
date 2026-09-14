import { useState } from 'react'
import { testConnectionDetails, testPrinterConnection } from '../api'
import type { MaterialProfileRecord, PrintHostType, PrinterRecord, PrinterUpdateRequest } from '../types'

interface ConnectionFields {
  host_type: PrintHostType | null
  print_host: string | null
  printhost_apikey: string | null
  printhost_user: string | null
  printhost_password: string | null
}

interface SavedPrintersProps {
  printers: PrinterRecord[]
  selectedPrinterId: string | null
  onSelectPrinter: (printer: PrinterRecord) => void
  canSaveCurrent: boolean
  onSavePrinter: (name: string, connection: ConnectionFields) => Promise<unknown>
  onUpdatePrinter: (id: string, body: PrinterUpdateRequest) => Promise<unknown>
  onDeletePrinter: (id: string) => void

  materials: MaterialProfileRecord[]
  selectedMaterialId: string | null
  onSelectMaterial: (material: MaterialProfileRecord) => void
  onDeselectMaterial: () => void
  onSaveMaterial: (name: string) => Promise<unknown>
  onUpdateMaterial: () => Promise<unknown>
  onRenameMaterial: (id: string, name: string) => Promise<unknown>
  onDuplicateMaterial: (id: string) => void
  onDeleteMaterial: (id: string) => void
}

// Shared by the create-printer form (testing connection details before the
// printer even exists, via the ad-hoc endpoint) and the per-printer
// Settings form (testing what's actually saved) -- same button/result/error
// UI either way, just a different `onTest` call underneath.
function TestConnectionButton({ onTest }: { onTest: () => Promise<{ message: string }> }) {
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = () => {
    setBusy(true)
    setResult(null)
    setError(null)
    onTest()
      .then((res) => setResult(res.message))
      .catch((err: Error) => setError(err.message))
      .finally(() => setBusy(false))
  }

  return (
    <div className="test-connection">
      <button type="button" className="preview-button" disabled={busy} onClick={run}>
        {busy ? 'Testing…' : 'Test connection'}
      </button>
      {result && <span className="job-hint">{result}</span>}
      {error && <span className="job-error">{error}</span>}
    </div>
  )
}

// A connection-details editor for one already-saved printer. Host
// type/address are shown pre-filled (PrinterRecord exposes both); the
// apikey/user/password fields never are (write-only, per the backend never
// returning them) -- left blank means "keep what's saved", typing something
// replaces it, and "Clear saved credentials" wipes all three explicitly.
function PrinterSettingsForm({
  printer,
  onUpdate,
  onClose,
}: {
  printer: PrinterRecord
  onUpdate: (id: string, body: PrinterUpdateRequest) => Promise<unknown>
  onClose: () => void
}) {
  const [name, setName] = useState(printer.name)
  const [hostType, setHostType] = useState<'' | PrintHostType>(printer.host_type ?? '')
  const [printHost, setPrintHost] = useState(printer.print_host ?? '')
  const [apiKey, setApiKey] = useState('')
  const [hostUser, setHostUser] = useState('')
  const [hostPassword, setHostPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const body: PrinterUpdateRequest = {
      name,
      host_type: hostType || null,
      print_host: printHost || null,
    }
    if (apiKey) body.printhost_apikey = apiKey
    if (hostUser) body.printhost_user = hostUser
    if (hostPassword) body.printhost_password = hostPassword
    onUpdate(printer.id, body)
      .then(() => onClose())
      .catch((err: Error) => setError(err.message))
      .finally(() => setBusy(false))
  }

  const clearCredentials = () => {
    setBusy(true)
    setError(null)
    onUpdate(printer.id, { printhost_apikey: '', printhost_user: '', printhost_password: '' })
      .then(() => {
        setApiKey('')
        setHostUser('')
        setHostPassword('')
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setBusy(false))
  }

  return (
    <form className="auth-form printer-settings-form" onSubmit={submit}>
      <label>
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        Connection
        <select value={hostType} onChange={(e) => setHostType(e.target.value as '' | PrintHostType)}>
          <option value="">None</option>
          <option value="moonraker">Klipper (Moonraker)</option>
          <option value="octoprint">OctoPrint</option>
        </select>
      </label>
      {hostType && (
        <>
          <label>
            Host (e.g. http://printer.local:7125)
            <input value={printHost} onChange={(e) => setPrintHost(e.target.value)} />
          </label>
          <label>
            API key {printer.has_credentials && '(leave blank to keep the saved one)'}
            <input value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
          </label>
          <label>
            HTTP username {printer.has_credentials && '(leave blank to keep the saved one)'}
            <input value={hostUser} onChange={(e) => setHostUser(e.target.value)} />
          </label>
          <label>
            HTTP password {printer.has_credentials && '(leave blank to keep the saved one)'}
            <input type="password" value={hostPassword} onChange={(e) => setHostPassword(e.target.value)} />
          </label>
          {printer.has_credentials && (
            <button type="button" className="link-button danger-text" disabled={busy} onClick={clearCredentials}>
              Clear saved credentials
            </button>
          )}
        </>
      )}
      <div className="auth-form-actions">
        <button type="submit" disabled={busy || !name}>
          {busy ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className="link-button" disabled={busy} onClick={onClose}>
          Cancel
        </button>
      </div>
      {error && <div className="job-error">{error}</div>}

      {/* Tests the *saved* connection, not whatever's mid-edit above --
          save first if you want to test a credential you just typed. */}
      {printer.print_host && <TestConnectionButton onTest={() => testPrinterConnection(printer.id)} />}
    </form>
  )
}

// One row in "Manage material profiles": name (or an inline rename input),
// Rename/Duplicate/Delete.
function MaterialManageRow({
  material,
  onRename,
  onDuplicate,
  onDelete,
}: {
  material: MaterialProfileRecord
  onRename: (id: string, name: string) => Promise<unknown>
  onDuplicate: (id: string) => void
  onDelete: (id: string) => void
}) {
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState(material.name)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submitRename = (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    onRename(material.id, name)
      .then(() => setRenaming(false))
      .catch((err: Error) => setError(err.message))
      .finally(() => setBusy(false))
  }

  if (renaming) {
    return (
      <li>
        <form className="rename-form" onSubmit={submitRename}>
          <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          <button type="submit" disabled={busy || !name}>
            {busy ? 'Saving…' : 'Save'}
          </button>
          <button
            type="button"
            className="link-button"
            disabled={busy}
            onClick={() => {
              setRenaming(false)
              setName(material.name)
              setError(null)
            }}
          >
            Cancel
          </button>
          {error && <span className="job-error">{error}</span>}
        </form>
      </li>
    )
  }

  return (
    <li>
      <span>{material.name}</span>
      <button type="button" className="link-button" onClick={() => setRenaming(true)}>
        Rename
      </button>
      <button type="button" className="link-button" onClick={() => onDuplicate(material.id)}>
        Duplicate
      </button>
      <button type="button" className="link-button job-delete" onClick={() => onDelete(material.id)}>
        Delete
      </button>
    </li>
  )
}

// Sits above PrinterSelect: pick a saved printer to instantly restore
// vendor/printer/process/filament/bed-size (no network round-trip -- see
// App.tsx's applySavedPrinter), or save the current selection as a new one.
// Once a saved printer is picked, a second row does the same for that
// printer's material profiles (quick+advanced settings snapshots).
export default function SavedPrinters({
  printers,
  selectedPrinterId,
  onSelectPrinter,
  canSaveCurrent,
  onSavePrinter,
  onUpdatePrinter,
  onDeletePrinter,
  materials,
  selectedMaterialId,
  onSelectMaterial,
  onDeselectMaterial,
  onSaveMaterial,
  onUpdateMaterial,
  onRenameMaterial,
  onDuplicateMaterial,
  onDeleteMaterial,
}: SavedPrintersProps) {
  const [savingPrinter, setSavingPrinter] = useState(false)
  const [printerName, setPrinterName] = useState('')
  const [hostType, setHostType] = useState<'' | PrintHostType>('')
  const [printHost, setPrintHost] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [hostUser, setHostUser] = useState('')
  const [hostPassword, setHostPassword] = useState('')
  const [printerError, setPrinterError] = useState<string | null>(null)
  const [printerBusy, setPrinterBusy] = useState(false)

  const [editingPrinterId, setEditingPrinterId] = useState<string | null>(null)

  const [savingMaterial, setSavingMaterial] = useState(false)
  const [materialName, setMaterialName] = useState('')
  const [materialError, setMaterialError] = useState<string | null>(null)
  const [materialBusy, setMaterialBusy] = useState(false)

  const [updateBusy, setUpdateBusy] = useState(false)
  const [updateDone, setUpdateDone] = useState(false)

  const resetPrinterForm = () => {
    setSavingPrinter(false)
    setPrinterName('')
    setHostType('')
    setPrintHost('')
    setApiKey('')
    setHostUser('')
    setHostPassword('')
    setPrinterError(null)
  }

  const submitPrinter = (e: React.FormEvent) => {
    e.preventDefault()
    setPrinterBusy(true)
    setPrinterError(null)
    onSavePrinter(printerName, {
      host_type: hostType || null,
      print_host: printHost || null,
      printhost_apikey: apiKey || null,
      printhost_user: hostUser || null,
      printhost_password: hostPassword || null,
    })
      .then(() => resetPrinterForm())
      .catch((err: Error) => setPrinterError(err.message))
      .finally(() => setPrinterBusy(false))
  }

  const submitMaterial = (e: React.FormEvent) => {
    e.preventDefault()
    setMaterialBusy(true)
    setMaterialError(null)
    onSaveMaterial(materialName)
      .then(() => {
        setSavingMaterial(false)
        setMaterialName('')
      })
      .catch((err: Error) => setMaterialError(err.message))
      .finally(() => setMaterialBusy(false))
  }

  const runUpdateMaterial = () => {
    setUpdateBusy(true)
    setUpdateDone(false)
    onUpdateMaterial()
      .then(() => setUpdateDone(true))
      .catch((err: Error) => alert(`Failed to update material profile: ${err.message}`))
      .finally(() => setUpdateBusy(false))
  }

  const selectedMaterial = materials.find((m) => m.id === selectedMaterialId) ?? null

  return (
    <div className="saved-printers">
      <div className="field-group">
        <label>
          Saved printer
          <select
            value={selectedPrinterId ?? ''}
            onChange={(e) => {
              const printer = printers.find((p) => p.id === e.target.value)
              if (printer) onSelectPrinter(printer)
            }}
          >
            <option value="">— choose a saved printer —</option>
            {printers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {!savingPrinter ? (
        <button
          type="button"
          className="link-button"
          disabled={!canSaveCurrent}
          onClick={() => setSavingPrinter(true)}
        >
          Save current setup as printer…
        </button>
      ) : (
        <form className="auth-form" onSubmit={submitPrinter}>
          <label>
            Name
            <input value={printerName} onChange={(e) => setPrinterName(e.target.value)} autoFocus />
          </label>
          <label>
            Connection (optional, for sending G-code directly to the printer)
            <select value={hostType} onChange={(e) => setHostType(e.target.value as '' | PrintHostType)}>
              <option value="">None</option>
              <option value="moonraker">Klipper (Moonraker)</option>
              <option value="octoprint">OctoPrint</option>
            </select>
          </label>
          {hostType && (
            <>
              <label>
                Host (e.g. http://printer.local:7125)
                <input value={printHost} onChange={(e) => setPrintHost(e.target.value)} />
              </label>
              <label>
                API key (if required)
                <input value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
              </label>
              <label>
                HTTP username (if behind basic auth)
                <input value={hostUser} onChange={(e) => setHostUser(e.target.value)} />
              </label>
              <label>
                HTTP password (if behind basic auth)
                <input
                  type="password"
                  value={hostPassword}
                  onChange={(e) => setHostPassword(e.target.value)}
                />
              </label>
              {printHost && (
                <TestConnectionButton
                  onTest={() =>
                    testConnectionDetails({
                      host_type: hostType || null,
                      print_host: printHost || null,
                      printhost_apikey: apiKey || null,
                      printhost_user: hostUser || null,
                      printhost_password: hostPassword || null,
                    })
                  }
                />
              )}
            </>
          )}
          <div className="auth-form-actions">
            <button type="submit" disabled={printerBusy || !printerName}>
              {printerBusy ? 'Saving…' : 'Save printer'}
            </button>
            <button type="button" className="link-button" disabled={printerBusy} onClick={resetPrinterForm}>
              Cancel
            </button>
          </div>
          {printerError && <div className="job-error">{printerError}</div>}
        </form>
      )}

      {printers.length > 0 && (
        <details className="job-history">
          <summary>Manage saved printers ({printers.length})</summary>
          <ul>
            {printers.map((p) => (
              <li key={p.id} className="printer-manage-row">
                <div className="printer-manage-header">
                  <span>{p.name}</span>
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => setEditingPrinterId((prev) => (prev === p.id ? null : p.id))}
                  >
                    {editingPrinterId === p.id ? 'Close' : 'Settings'}
                  </button>
                  <button
                    type="button"
                    className="link-button job-delete"
                    onClick={() => onDeletePrinter(p.id)}
                  >
                    Delete
                  </button>
                </div>
                {editingPrinterId === p.id && (
                  <PrinterSettingsForm
                    printer={p}
                    onUpdate={onUpdatePrinter}
                    onClose={() => setEditingPrinterId(null)}
                  />
                )}
              </li>
            ))}
          </ul>
        </details>
      )}

      {selectedPrinterId && (
        <div className="material-profiles">
          <div className="field-group">
            <label>
              Material profile
              <select
                value={selectedMaterialId ?? ''}
                onChange={(e) => {
                  const material = materials.find((m) => m.id === e.target.value)
                  if (material) onSelectMaterial(material)
                  else onDeselectMaterial()
                }}
              >
                <option value="">— choose a material profile —</option>
                {materials.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {selectedMaterial && (
            <div className="material-update-actions">
              <button type="button" className="preview-button" disabled={updateBusy} onClick={runUpdateMaterial}>
                {updateBusy ? 'Updating…' : `Update "${selectedMaterial.name}"`}
              </button>
              {updateDone && <span className="job-hint">Updated.</span>}
            </div>
          )}

          {!savingMaterial ? (
            <button type="button" className="link-button" onClick={() => setSavingMaterial(true)}>
              {selectedMaterial ? 'Save as new profile…' : 'Save current settings as a material profile…'}
            </button>
          ) : (
            <form className="auth-form" onSubmit={submitMaterial}>
              <label>
                Name (e.g. "PLA", "PETG")
                <input value={materialName} onChange={(e) => setMaterialName(e.target.value)} autoFocus />
              </label>
              <div className="auth-form-actions">
                <button type="submit" disabled={materialBusy || !materialName}>
                  {materialBusy ? 'Saving…' : 'Save material profile'}
                </button>
                <button
                  type="button"
                  className="link-button"
                  disabled={materialBusy}
                  onClick={() => {
                    setSavingMaterial(false)
                    setMaterialName('')
                    setMaterialError(null)
                  }}
                >
                  Cancel
                </button>
              </div>
              {materialError && <div className="job-error">{materialError}</div>}
            </form>
          )}

          {materials.length > 0 && (
            <details className="job-history">
              <summary>Manage material profiles ({materials.length})</summary>
              <ul>
                {materials.map((m) => (
                  <MaterialManageRow
                    key={m.id}
                    material={m}
                    onRename={onRenameMaterial}
                    onDuplicate={onDuplicateMaterial}
                    onDelete={onDeleteMaterial}
                  />
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  )
}
