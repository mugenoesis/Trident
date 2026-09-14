import { useCallback, useEffect, useState } from 'react'
import {
  createUser as apiCreateUser,
  getAuthStatus,
  login as apiLogin,
  logout as apiLogout,
  setupAuth,
  switchToMulti as apiSwitchToMulti,
  switchToSingle as apiSwitchToSingle,
  updateLastSelection as apiUpdateLastSelection,
} from './api'
import type { AuthStatus } from './types'

// Centralizes the first-run/login/settings-menu auth flow so App.tsx's
// render logic can just branch on `status` rather than juggling its own
// fetch/loading state for each action.
export function useAuth() {
  const [status, setStatus] = useState<AuthStatus | null>(null)

  const refresh = useCallback(() => getAuthStatus().then(setStatus), [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const setup = useCallback(
    (body: { mode: 'single' } | { mode: 'multi'; username: string; password: string }) =>
      setupAuth(body).then(setStatus),
    [],
  )
  const login = useCallback(
    (username: string, password: string) => apiLogin(username, password).then(setStatus),
    [],
  )
  const logout = useCallback(() => apiLogout().then(() => refresh()), [refresh])
  const switchToMulti = useCallback(
    (username: string, password: string) => apiSwitchToMulti(username, password).then(setStatus),
    [],
  )
  const createUser = useCallback(
    (username: string, password: string) => apiCreateUser(username, password).then(setStatus),
    [],
  )
  const switchToSingle = useCallback(() => apiSwitchToSingle().then(setStatus), [])
  const updateLastSelection = useCallback(
    (printerId: string | null, materialId: string | null) =>
      apiUpdateLastSelection(printerId, materialId).then(setStatus),
    [],
  )

  return {
    status,
    setup,
    login,
    logout,
    switchToMulti,
    switchToSingle,
    createUser,
    updateLastSelection,
  }
}
