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
  user_id: string
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

// "unset": fresh install, no mode chosen yet -- behaves like "single"
// server-side, but the frontend uses it to show the first-run picker.
export type AuthMode = 'unset' | 'single' | 'multi'

export interface AuthStatus {
  mode: AuthMode
  logged_in: boolean
  username: string | null
}

// The only two host_type values the backend's printhost client actually
// knows how to talk to (see api/app/printhost.py) -- the value stored can
// technically be any OrcaSlicer host_type string, but the UI only offers
// these two since anything else can't be sent to yet.
export type PrintHostType = 'octoprint' | 'moonraker'

export interface PrinterConnection {
  host_type: PrintHostType | null
  print_host: string | null
  printhost_apikey: string | null
  printhost_user: string | null
  printhost_password: string | null
}

export interface PrinterRecord extends PrinterConnection {
  id: string
  name: string
  vendor: string
  machine_profile: string
  process_profile: string
  filament_profile: string
  bed_width: number | null
  bed_depth: number | null
  bed_height: number | null
  has_credentials: boolean
  created_at: string
}

export interface PrinterCreateRequest extends PrinterConnection {
  name: string
  vendor: string
  machine_profile: string
  process_profile: string
  filament_profile: string
  bed_width: number | null
  bed_depth: number | null
  bed_height: number | null
}

export interface MaterialProfileRecord {
  id: string
  printer_id: string
  name: string
  quick_settings: Record<string, string>
  advanced_overrides: Record<string, string>
  process_profile: string | null
  filament_profile: string | null
  created_at: string
}

export interface MaterialProfileCreateRequest {
  name: string
  quick_settings: Record<string, string>
  advanced_overrides: Record<string, string>
  process_profile: string | null
  filament_profile: string | null
}
