import { useState } from 'react'
import { testConnectionDetails, testPrinterConnection } from '../api'
import type { PrintHostType, PrinterRecord, PrinterUpdateRequest } from '../types'

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

// Sits above PrinterSelect: pick a saved printer to instantly restore
// vendor/printer/process/filament/bed-size (no network round-trip -- see
// App.tsx's applySavedPrinter), or save the current selection as a new one.
// Material profiles and settings profiles are separate, independently
// saveable concepts once a printer is selected -- see SavedProfilePicker,
// rendered from App.tsx's "Material"/"Settings" sections, not here.
export default function SavedPrinters({
  printers,
  selectedPrinterId,
  onSelectPrinter,
  canSaveCurrent,
  onSavePrinter,
  onUpdatePrinter,
  onDeletePrinter,
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
    </div>
  )
}
