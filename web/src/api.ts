import type {
  AuthStatus,
  JobCreateRequest,
  JobRecord,
  MaterialProfileCreateRequest,
  MaterialProfileRecord,
  ModelUploadResponse,
  PrinterCreateRequest,
  PrinterRecord,
  ProfileDetail,
  ProfileSummary,
  SettingsSchema,
} from './types'

// In production the built frontend is served by the same FastAPI app
// (see api/app/main.py's StaticFiles mount), so relative paths hit the
// right place. In dev (`npm run dev`, Vite on :5173) the API runs
// separately -- point straight at it (the API's permissive CORS middleware
// exists for exactly this).
const API_BASE = import.meta.env.DEV ? 'http://localhost:8000' : ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // 'include' rather than the same-origin default: needed for the session
  // cookie to actually be sent/set during `npm run dev`, where the frontend
  // (:5173) and API (:8000) are different origins. Harmless in production,
  // where it's same-origin anyway.
  const res = await fetch(`${API_BASE}${path}`, { credentials: 'include', ...init })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // response wasn't JSON; keep statusText
    }
    throw new Error(`${res.status} ${detail}`)
  }
  return res.json() as Promise<T>
}

export function listProfiles(): Promise<ProfileSummary[]> {
  return request('/profiles')
}

export function getProfileDetail(
  vendor: string,
  kind: string,
  name: string,
): Promise<ProfileDetail> {
  return request(
    `/profiles/${encodeURIComponent(vendor)}/${encodeURIComponent(kind)}/${encodeURIComponent(name)}`,
  )
}

export function getSettingsSchema(): Promise<SettingsSchema> {
  return request('/settings/schema')
}

export async function uploadModel(file: File): Promise<ModelUploadResponse> {
  const form = new FormData()
  form.append('file', file)
  return request('/models', { method: 'POST', body: form })
}

export function createJob(req: JobCreateRequest): Promise<JobRecord> {
  return request('/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
}

export function getJob(id: string): Promise<JobRecord> {
  return request(`/jobs/${id}`)
}

export function listJobs(): Promise<JobRecord[]> {
  return request('/jobs')
}

export function deleteJob(id: string): Promise<{ ok: boolean }> {
  return request(`/jobs/${id}`, { method: 'DELETE' })
}

export function gcodeDownloadUrl(id: string): string {
  return `${API_BASE}/jobs/${id}/gcode`
}

export function thumbnailUrl(id: string): string {
  return `${API_BASE}/jobs/${id}/thumbnail`
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function getAuthStatus(): Promise<AuthStatus> {
  return request('/auth/status')
}

export function setupAuth(
  body: { mode: 'single' } | { mode: 'multi'; username: string; password: string },
): Promise<AuthStatus> {
  return postJson('/auth/setup', body)
}

export function login(username: string, password: string): Promise<AuthStatus> {
  return postJson('/auth/login', { username, password })
}

export function logout(): Promise<{ ok: boolean }> {
  return postJson('/auth/logout', {})
}

export function switchToMulti(username: string, password: string): Promise<AuthStatus> {
  return postJson('/auth/switch-to-multi', { username, password })
}

export function switchToSingle(): Promise<AuthStatus> {
  return postJson('/auth/switch-to-single', {})
}

export function listPrinters(): Promise<PrinterRecord[]> {
  return request('/printers')
}

export function createPrinter(req: PrinterCreateRequest): Promise<PrinterRecord> {
  return postJson('/printers', req)
}

export function deletePrinter(id: string): Promise<{ ok: boolean }> {
  return request(`/printers/${id}`, { method: 'DELETE' })
}

export function listMaterialProfiles(printerId: string): Promise<MaterialProfileRecord[]> {
  return request(`/printers/${printerId}/materials`)
}

export function createMaterialProfile(
  printerId: string,
  req: MaterialProfileCreateRequest,
): Promise<MaterialProfileRecord> {
  return postJson(`/printers/${printerId}/materials`, req)
}

export function deleteMaterialProfile(printerId: string, materialId: string): Promise<{ ok: boolean }> {
  return request(`/printers/${printerId}/materials/${materialId}`, { method: 'DELETE' })
}

export function sendToPrinter(
  printerId: string,
  jobId: string,
  startPrint: boolean,
): Promise<{ ok: boolean }> {
  return postJson(`/printers/${printerId}/send/${jobId}`, { start_print: startPrint })
}

export function createUser(username: string, password: string): Promise<AuthStatus> {
  return postJson('/auth/users', { username, password })
}
