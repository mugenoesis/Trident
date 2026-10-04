import { useState } from 'react'

interface SetupGateProps {
  onChooseSingle: () => Promise<unknown>
  onChooseMulti: (username: string, password: string) => Promise<unknown>
}

// First-run only: shown once, while auth mode is still "unset". Single-user
// is one click; multi-user asks for the first account's credentials inline
// before submitting, since /auth/setup creates that account atomically with
// picking the mode.
export default function SetupGate({ onChooseSingle, onChooseMulti }: SetupGateProps) {
  const [mode, setMode] = useState<'choose' | 'multi'>('choose')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const chooseSingle = () => {
    setBusy(true)
    setError(null)
    onChooseSingle().catch((err: Error) => {
      setError(err.message)
      setBusy(false)
    })
  }

  const submitMulti = (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    onChooseMulti(username, password).catch((err: Error) => {
      setError(err.message)
      setBusy(false)
    })
  }

  return (
    <div className="auth-gate">
      <div className="auth-card">
        <h2>Welcome to TridentSlicer</h2>
        {mode === 'choose' && (
          <>
            <p className="auth-copy">How do you want to use this?</p>
            <div className="auth-choice-list">
              <button type="button" disabled={busy} onClick={chooseSingle}>
                Just me (no login)
              </button>
              <button type="button" disabled={busy} className="preview-button" onClick={() => setMode('multi')}>
                Multiple people (accounts)
              </button>
            </div>
            <p className="auth-hint">
              You can switch between single- and multi-user later from the settings menu.
              Switching back to single-user merges everyone&rsquo;s printers and job history into
              one shared, login-free setup &mdash; nothing is lost, but accounts can&rsquo;t be
              split apart again afterward.
            </p>
          </>
        )}
        {mode === 'multi' && (
          <form onSubmit={submitMulti} className="auth-form">
            <p className="auth-copy">Create the first account:</p>
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
                {busy ? 'Creating…' : 'Create account'}
              </button>
              <button type="button" className="link-button" disabled={busy} onClick={() => setMode('choose')}>
                Back
              </button>
            </div>
          </form>
        )}
        {error && <div className="job-error">{error}</div>}
      </div>
    </div>
  )
}
