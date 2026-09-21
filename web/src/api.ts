import type {
  AuthStatus,
  JobCreateRequest,
  JobRecord,
  MaterialProfileCreateRequest,
  MaterialProfileRecord,
  MaterialProfileUpdateRequest,
  ModelUploadResponse,
  PrinterConnection,
  PrinterCreateRequest,
  PrinterRecord,
  PrinterUpdateRequest,
  ProfileDetail,
  ProfileSummary,
  SampleModelSummary,
  SettingsProfileCreateRequest,
  SettingsProfileRecord,
  SettingsProfileUpdateRequest,
  SettingsSchema,
  ThreeMfInspection,
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

export function listSampleModels(): Promise<SampleModelSummary[]> {
  return request('/sample-models')
}

export function loadSampleModel(sampleId: string): Promise<ModelUploadResponse> {
  return request(`/sample-models/${encodeURIComponent(sampleId)}/load`, { method: 'POST' })
}

// Re-fetches a model's original bytes into a browser-side File -- needed
// for a sample model (loaded server-side, so the browser never held the
// bytes the way it does for a local upload) to get the same 3D preview an
// upload gets. The filename comes from Content-Disposition so a sample's
// display name (e.g. "3DBenchy") round-trips into the File's own name.
export async function downloadModelFile(modelId: string): Promise<File> {
  const res = await fetch(`${API_BASE}/models/${encodeURIComponent(modelId)}/file`, {
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  const disposition = res.headers.get('Content-Disposition') ?? ''
  // Starlette's FileResponse only uses the plain filename="..." form when
  // the name needs no encoding -- any name with a space (every bundled
  // sample model except "3DBenchy") gets the RFC 5987 filename*=UTF-8''
  // <percent-encoded> form instead, which must be decodeURIComponent'd,
  // not read literally as if it were the plain form. Missing this meant
  // every multi-word sample silently fell back to using the bare model_id
  // (no extension) as its filename, which made the viewer misdetect it as
  // a plain STL and feed raw 3MF/Draco bytes into STLLoader.
  const encodedMatch = /filename\*=[^']*''([^;]+)/i.exec(disposition)
  const plainMatch = /filename="?([^";]+)"?/i.exec(disposition)
  const filename = encodedMatch ? decodeURIComponent(encodedMatch[1]) : (plainMatch?.[1] ?? modelId)
  const blob = await res.blob()
  return new File([blob], filename)
}

export function getModelPlates(modelId: string): Promise<ThreeMfInspection> {
  return request(`/models/${encodeURIComponent(modelId)}/plates`)
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

function putJson<T>(path: string, body: unknown): Promise<T> {
  return request(path, {
    method: 'PUT',
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

export function updateLastSelection(
  printerId: string | null,
  materialId: string | null,
): Promise<AuthStatus> {
  return putJson('/auth/last-selection', { printer_id: printerId, material_id: materialId })
}

export function listPrinters(): Promise<PrinterRecord[]> {
  return request('/printers')
}

export function createPrinter(req: PrinterCreateRequest): Promise<PrinterRecord> {
  return postJson('/printers', req)
}

export function updatePrinter(id: string, req: PrinterUpdateRequest): Promise<PrinterRecord> {
  return putJson(`/printers/${id}`, req)
}

export function deletePrinter(id: string): Promise<{ ok: boolean }> {
  return request(`/printers/${id}`, { method: 'DELETE' })
}

export function testPrinterConnection(id: string): Promise<{ message: string }> {
  return postJson(`/printers/${id}/test-connection`, {})
}

// Ad-hoc variant: validates connection fields before a printer is even
// saved (used by the create-printer form's Test connection button).
export function testConnectionDetails(connection: PrinterConnection): Promise<{ message: string }> {
  return postJson('/printers/test-connection', connection)
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

export function updateMaterialProfile(
  printerId: string,
  materialId: string,
  req: MaterialProfileUpdateRequest,
): Promise<MaterialProfileRecord> {
  return putJson(`/printers/${printerId}/materials/${materialId}`, req)
}

export function duplicateMaterialProfile(
  printerId: string,
  materialId: string,
): Promise<MaterialProfileRecord> {
  return postJson(`/printers/${printerId}/materials/${materialId}/duplicate`, {})
}

export function deleteMaterialProfile(printerId: string, materialId: string): Promise<{ ok: boolean }> {
  return request(`/printers/${printerId}/materials/${materialId}`, { method: 'DELETE' })
}

export function listSettingsProfiles(printerId: string): Promise<SettingsProfileRecord[]> {
  return request(`/printers/${printerId}/settings-profiles`)
}

export function createSettingsProfile(
  printerId: string,
  req: SettingsProfileCreateRequest,
): Promise<SettingsProfileRecord> {
  return postJson(`/printers/${printerId}/settings-profiles`, req)
}

export function updateSettingsProfile(
  printerId: string,
  profileId: string,
  req: SettingsProfileUpdateRequest,
): Promise<SettingsProfileRecord> {
  return putJson(`/printers/${printerId}/settings-profiles/${profileId}`, req)
}

export function duplicateSettingsProfile(
  printerId: string,
  profileId: string,
): Promise<SettingsProfileRecord> {
  return postJson(`/printers/${printerId}/settings-profiles/${profileId}/duplicate`, {})
}

export function deleteSettingsProfile(printerId: string, profileId: string): Promise<{ ok: boolean }> {
  return request(`/printers/${printerId}/settings-profiles/${profileId}`, { method: 'DELETE' })
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
