import type {
  JobCreateRequest,
  JobRecord,
  ModelUploadResponse,
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
  const res = await fetch(`${API_BASE}${path}`, init)
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

export function gcodeDownloadUrl(id: string): string {
  return `${API_BASE}/jobs/${id}/gcode`
}

export function thumbnailUrl(id: string): string {
  return `${API_BASE}/jobs/${id}/thumbnail`
}
