import { useState } from 'react'

interface LoginGateProps {
  onLogin: (username: string, password: string) => Promise<unknown>
}

export default function LoginGate({ onLogin }: LoginGateProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    onLogin(username, password).catch((err: Error) => {
      setError(err.message)
      setBusy(false)
    })
  }

  return (
    <div className="auth-gate">
      <div className="auth-card">
        <img className="auth-logo" src="/icon-192.png" alt="Trident logo" width={96} height={96} />
        <h2>Sign in</h2>
        <form onSubmit={submit} className="auth-form">
          <label>
            Username
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <div className="auth-form-actions">
            <button type="submit" disabled={busy || !username || !password}>
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </div>
        </form>
        {error && <div className="job-error">{error}</div>}
      </div>
    </div>
  )
}
