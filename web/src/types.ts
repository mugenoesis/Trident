// Mirrors api/app/schemas.py. Keep in sync by hand -- this project has no
// shared schema generation step.

export interface ProfileSummary {
  vendor: string
  kind: 'machine' | 'process' | 'filament' | 'unknown'
  name: string
  path: string
  // Printers a user-made material is limited to (empty or absent = every printer).
  compatible_printers?: string[]
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

// What the upload-time STL check found (api/app/meshcheck.py): `fixed` are
// defects the slicer repairs by itself, `warnings` ones it does not.
export interface MeshReport {
  fixed: string[]
  warnings: string[]
}

export interface ModelUploadResponse {
  model_id: string
  filename: string
  mesh_report?: MeshReport | null
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
  // Put the whole model at an exact spot (not combined with belt_layout).
  placement?: Placement
  // Print this many copies of the whole (selected) model.
  copies?: number
  // .3mf only: indices of objects NOT to print.
  excluded_objects?: number[]
  // .3mf on a belt printer only: lay the kept objects out in a row.
  belt_layout?: BeltLayout
  // Raw base64 PNG (no "data:" prefix), a snapshot of the 3D preview at the
  // moment slicing starts -- embedded into the gcode's own thumbnail
  // server-side (api/app/gcode_thumbnail.py), since the OrcaSlicer CLI
  // never renders one itself. Omitted entirely when nothing was loaded to
  // capture.
  preview_image_base64?: string
}

export interface PlateInfo {
  index: number
  name: string | null
  object_count: number | null
  thumbnail: string | null
}

// One <build><item> of a .3mf, in file order -- index lines up with the
// viewer's per-object meshes (see api/app/threemf_objects.py).
export interface ObjectInfo {
  index: number
  name: string
  plate: number
  width_mm: number
  depth_mm: number
  height_mm: number
  // Centre of the object in plate coordinates (mm), where the file puts it.
  center_x_mm: number
  center_y_mm: number
}

// Where to put the model: the centre of its footprint, in plate coordinates.
export interface Placement {
  x: number
  y: number
}

export interface BeltLayout {
  order: number[]
  gap_mm: number
  // A file on several plates: lay each plate out as one block, one after another ('plates'), or put
  // every object in a single row ('objects').
  mode?: 'plates' | 'objects'
}

export interface ThreeMfInspection {
  plates: PlateInfo[]
  // Empty for anything but a .3mf whose objects could be read.
  objects?: ObjectInfo[]
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
  // object/part color info to place (a plain file with no material split
  // at all).
  color_tree: ColorNode[]
}

export interface ColorNode {
  color: string | null
  // This leaf's 1-based extruder/filament-role index (null for a
  // composite, or a leaf with no resolvable extruder) -- `color` is that
  // role's color as the file's own author set it; App.tsx uses this index
  // (extruder - 1 == the role's position in embedded_filament_colors /
  // roleNozzleAssignments) to substitute whichever color the user actually
  // assigned that role to, once they've picked a nozzle for it.
  extruder: number | null
  children: ColorNode[]
  // One entry per triangle in this leaf's own mesh, same order as its
  // <triangle> elements (and so the loaded 3D geometry's face order) --
  // present only on a leaf with real per-triangle paint overrides (a
  // hand-painted multi-color part, e.g. from MakerWorld/Bambu Studio);
  // null for a composite, and for a leaf with no paint data at all (the
  // common case, already fully described by color/extruder alone). A
  // deliberate one-representative-color-per-original-triangle
  // approximation, not a sub-triangle-accurate split -- see
  // api/app/threemf.py's _representative_extruder. Same
  // extruder->color/live-reassignment substitution as the singular
  // extruder/color pair above, just per-triangle.
  triangle_extruders: (number | null)[] | null
  triangle_colors: (string | null)[] | null
}

// "unset": fresh install, no mode chosen yet -- behaves like "single"
// server-side, but the frontend uses it to show the first-run picker.
export type AuthMode = 'unset' | 'single' | 'multi'

export interface AuthStatus {
  mode: AuthMode
  logged_in: boolean
  username: string | null
  // The printer/material/settings profile last selected -- App.tsx restores
  // these as the default once the matching printers/materials/settings-
  // profiles list has loaded.
  last_printer_id: string | null
  last_material_id: string | null
  last_settings_profile_id: string | null
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

// Filament choice only -- print-quality settings live separately in a
// SettingsProfileRecord, saved/loaded independently (see below).
export interface MaterialProfileRecord {
  id: string
  printer_id: string
  name: string
  filament_profiles: string[] | null
  filament_colors: string[] | null
  created_at: string
}

export interface MaterialProfileCreateRequest {
  name: string
  filament_profiles: string[] | null
  filament_colors: string[] | null
}

// A key left out entirely means "don't change" (see api/app/schemas.py's
// MaterialProfileUpdateRequest) -- used for both a plain rename ({name})
// and "update mode" (overwrite the saved filament choice).
export interface MaterialProfileUpdateRequest {
  name?: string
  filament_profiles?: string[] | null
  filament_colors?: string[] | null
}

// The counterpart to MaterialProfileRecord: print-quality settings only, no
// filament choice, so the same materials can be reused across quality
// presets and vice versa.
export interface SettingsProfileRecord {
  id: string
  printer_id: string
  name: string
  quick_settings: Record<string, string>
  advanced_overrides: Record<string, string>
  process_profile: string | null
  created_at: string
}

export interface SettingsProfileCreateRequest {
  name: string
  quick_settings: Record<string, string>
  advanced_overrides: Record<string, string>
  process_profile: string | null
}

export interface SettingsProfileUpdateRequest {
  name?: string
  quick_settings?: Record<string, string>
  advanced_overrides?: Record<string, string>
  process_profile?: string | null
}

// Result of importing profile files (api/app/userprofiles.py).
// The "New material" form (POST/PUT /profiles/filaments).
export interface FilamentForm {
  name: string
  base_name?: string
  filament_type: string
  filament_vendor: string
  nozzle_temperature: number
  nozzle_temperature_initial_layer: number
  nozzle_temperature_range_low: number
  nozzle_temperature_range_high: number
  plate_temps: Record<string, number>
  filament_flow_ratio: number
  filament_max_volumetric_speed: number
  filament_density: number
  filament_diameter: number
  fan_min_speed: number
  fan_max_speed: number
  // Printers (machine profile names) the material is limited to; empty = every printer.
  printers?: string[]
}

export interface ImportedProfile {
  kind: string // 'machine' | 'process' | 'filament'
  name: string
  inherits?: string | null
  warning?: string | null
}

export interface ImportIssue {
  file: string
  name?: string | null
  reason: string
}

export interface ImportResult {
  imported: ImportedProfile[]
  // Same name already imported earlier and overwrite was off.
  conflicts: ImportedProfile[]
  skipped: ImportIssue[]
}

// One step of POST /models/{id}/transform (api/app/schemas.py TransformStep).
export type TransformStep =
  | { op: 'rotate_x' | 'rotate_y' | 'rotate_z'; degrees: number }
  | { op: 'lay_flat' }
  | { op: 'face_normal'; normal: [number, number, number] }

// One object of POST /models/{id}/transform-objects (api/app/schemas.py ObjectEdit): turned
// (degrees, X then Y then Z about the plate's axes) and placed with its footprint centre at (x, y).
export interface ObjectEdit {
  index: number
  x_deg: number
  y_deg: number
  z_deg: number
  x: number
  y: number
}
