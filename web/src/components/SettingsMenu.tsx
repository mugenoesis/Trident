import { useState } from 'react'
import type { AuthStatus } from '../types'

interface SettingsMenuProps {
  status: AuthStatus
  onSwitchToMulti: (username: string, password: string) => Promise<unknown>
  onCreateUser: (username: string, password: string) => Promise<unknown>
  onLogout: () => Promise<unknown>
}

// Small header gear -> dropdown panel. The only place mode/account
// management lives outside the first-run gate: switching single -> multi,
// adding a household account, and logging out.
export default function SettingsMenu({ status, onSwitchToMulti, onCreateUser, onLogout }: SettingsMenuProps) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<'none' | 'switch' | 'add'>('none')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const resetForm = () => {
    setForm('none')
    setUsername('')
    setPassword('')
    setError(null)
  }

  const submit = (action: (u: string, p: string) => Promise<unknown>) => (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    action(username, password)
      .then(() => resetForm())
      .catch((err: Error) => setError(err.message))
      .finally(() => setBusy(false))
  }

  return (
    <div className="settings-menu">
      <button
        type="button"
        className="settings-gear"
        aria-label="Settings"
        onClick={() => {
          setOpen((o) => !o)
          resetForm()
        }}
      >
        ⚙
      </button>
      {open && (
        <div className="settings-panel">
          {status.mode === 'single' && form === 'none' && (
            <>
              <div className="settings-status">Single-user mode</div>
              <button type="button" className="link-button" onClick={() => setForm('switch')}>
                Switch to multi-user…
              </button>
            </>
          )}
          {status.mode === 'multi' && form === 'none' && (
            <>
              <div className="settings-status">Signed in as {status.username}</div>
              <button type="button" className="link-button" onClick={() => setForm('add')}>
                Add another user…
              </button>
              <button type="button" className="link-button" onClick={() => onLogout()}>
                Log out
              </button>
            </>
          )}
          {(form === 'switch' || form === 'add') && (
            <form
              className="auth-form"
              onSubmit={submit(form === 'switch' ? onSwitchToMulti : onCreateUser)}
            >
              {form === 'switch' && (
                <p className="auth-hint">
                  This can&rsquo;t be undone -- your existing printers and job history stay
                  attached to this account.
                </p>
              )}
              <label>
                Username
                <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
              </label>
              <label>
                Password
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </label>
              <div className="auth-form-actions">
                <button type="submit" disabled={busy || !username || !password}>
                  {busy ? 'Saving…' : form === 'switch' ? 'Switch to multi-user' : 'Create user'}
                </button>
                <button type="button" className="link-button" disabled={busy} onClick={resetForm}>
                  Cancel
                </button>
              </div>
              {error && <div className="job-error">{error}</div>}
            </form>
          )}
        </div>
      )}
    </div>
  )
}
