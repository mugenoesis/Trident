// Mirrors api/app/schemas.py. Keep in sync by hand -- this project has no
// shared schema generation step.

export interface ProfileSummary {
  vendor: string
  kind: 'machine' | 'process' | 'filament' | 'unknown'
  name: string
  path: string
}

export interface ProfileDetail extends ProfileSummary {
  data: Record<string, unknown>
}

export interface SettingDef {
  key: string
  type: string
  label: string | null
  description: string | null
  enum_values: string[] | null
  default: unknown
}

export interface SettingsSchema {
  source: string
  settings: SettingDef[]
}

export interface ModelUploadResponse {
  model_id: string
  filename: string
}

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed'

export interface JobProgress {
  plate_index: number | null
  plate_count: number | null
  plate_percent: number | null
  total_percent: number | null
  message: string | null
  warning: string | null
}

export interface JobRecord {
  id: string
  status: JobStatus
  model_id: string
  printer_profile: string
  process_profile: string
  filament_profiles: string[]
  setting_overrides: Record<string, unknown>
  created_at: string
  updated_at: string
  progress: JobProgress | null
  result: Record<string, unknown> | null
  error: string | null
}

export interface JobCreateRequest {
  model_id: string
  printer_profile: string
  process_profile: string
  filament_profiles: string[]
  setting_overrides: Record<string, unknown>
}
