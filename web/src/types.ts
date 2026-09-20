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

export interface SampleModelSummary {
  id: string
  name: string
  description: string
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
  plate_index: number | null
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
  plate_index?: number | null
}

export interface PlateInfo {
  index: number
  name: string | null
  object_count: number | null
  thumbnail: string | null
}

export interface ThreeMfInspection {
  plates: PlateInfo[]
  extruder_indices: number[]
  // The file's own author's filament_colour array, one entry per filament
  // role the file was originally configured with -- more reliable than
  // extruder_indices for detecting real multi-material intent (catches
  // paint-on/per-triangle color assignments that per-object extruder
  // metadata misses entirely). An empty string means "role exists, no
  // known color" rather than "no role" -- length is what matters.
  embedded_filament_colors: string[]
  // The file's own author's saved material name per role (e.g. "Bambu
  // PLA Basic @BBL A1M"), same index space as embedded_filament_colors --
  // shown next to a role's swatch purely to help matching it to one of
  // your own materials; never an actual profile in your own catalog.
  embedded_filament_names: string[]
  // One entry per top-level object placed in the file (<build><item>
  // order), mirroring the exact tree three.js's 3MFLoader itself builds
  // (a composite object's Group children come from <components> in the
  // same order) -- Viewer.tsx walks its rendered Object3D tree in
  // lockstep with this to color each mesh. Empty when there's no per-
  // object/part color info to place (covers plain files and ones whose
  // color is only per-triangle paint, which isn't parsed server-side).
  color_tree: ColorNode[]
}

export interface ColorNode {
  color: string | null
  children: ColorNode[]
}

// "unset": fresh install, no mode chosen yet -- behaves like "single"
// server-side, but the frontend uses it to show the first-run picker.
export type AuthMode = 'unset' | 'single' | 'multi'

export interface AuthStatus {
  mode: AuthMode
  logged_in: boolean
  username: string | null
  // The printer/material profile last selected -- App.tsx restores these
  // as the default once the matching printers/materials list has loaded.
  last_printer_id: string | null
  last_material_id: string | null
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
  // One entry per physical extruder/AMS slot, index-aligned with
  // filament_colors (e.g. Snapmaker U1's several independent heads, or
  // Bambu X1C's several AMS slots feeding one nozzle).
  filament_profiles: string[]
  filament_colors: string[] // "#rrggbb", UI label only -- never sent to OrcaSlicer
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
  filament_profiles: string[]
  filament_colors: string[]
  bed_width: number | null
  bed_depth: number | null
  bed_height: number | null
}

// A key left out entirely means "don't change" (see api/app/schemas.py's
// PrinterUpdateRequest); an empty string for a secret field means "clear
// it". Only name + connection fields are editable -- a printer's slicing
// identity (vendor/machine/process/filament/bed size) is delete-and-recreate.
export interface PrinterUpdateRequest {
  name?: string
  host_type?: PrintHostType | null
  print_host?: string | null
  printhost_apikey?: string
  printhost_user?: string
  printhost_password?: string
}

export interface MaterialProfileRecord {
  id: string
  printer_id: string
  name: string
  quick_settings: Record<string, string>
  advanced_overrides: Record<string, string>
  process_profile: string | null
  filament_profiles: string[] | null
  filament_colors: string[] | null
  created_at: string
}

export interface MaterialProfileCreateRequest {
  name: string
  quick_settings: Record<string, string>
  advanced_overrides: Record<string, string>
  process_profile: string | null
  filament_profiles: string[] | null
  filament_colors: string[] | null
}

// A key left out entirely means "don't change" (see api/app/schemas.py's
// MaterialProfileUpdateRequest) -- used for both a plain rename ({name})
// and "update mode" (overwrite the saved settings: {quick_settings, ...}).
export interface MaterialProfileUpdateRequest {
  name?: string
  quick_settings?: Record<string, string>
  advanced_overrides?: Record<string, string>
  process_profile?: string | null
  filament_profiles?: string[] | null
  filament_colors?: string[] | null
}
