import { useState } from 'react'
import type { PrinterRecord } from '../types'

interface SendToPrinterControlProps {
  printer: PrinterRecord
  jobId: string
  onSend: (jobId: string, startPrint: boolean) => Promise<unknown>
}

// Rendered alongside GcodeViewer (App.tsx), not buried down in JobPanel's
// settings column -- slicing scrolls the page back to the G-code view, so
// anything you'd want to do right after (download, send) needs to live up
// there too, or it's an extra scroll back down every single time.
export default function SendToPrinterControl({ printer, jobId, onSend }: SendToPrinterControlProps) {
  const [startPrint, setStartPrint] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<'idle' | 'sent' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)

  const send = () => {
    setBusy(true)
    setResult('idle')
    setError(null)
    onSend(jobId, startPrint)
      .then(() => setResult('sent'))
      .catch((err: Error) => {
        setResult('error')
        setError(err.message)
      })
      .finally(() => setBusy(false))
  }

  return (
    <div className="send-to-printer">
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={startPrint}
          onChange={(e) => setStartPrint(e.target.checked)}
        />
        Start printing immediately
      </label>
      <button type="button" className="preview-button" disabled={busy} onClick={send}>
        {busy ? 'Sending…' : `Send to ${printer.name}`}
      </button>
      {result === 'sent' && <div className="job-hint">Sent to {printer.name}.</div>}
      {result === 'error' && <div className="job-error">{error}</div>}
    </div>
  )
}
