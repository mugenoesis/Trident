import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import {
  arrangeModel,
  createJob,
  deleteImportedProfile,
  createMaterialProfile,
  createPrinter,
  createSettingsProfile,
  deleteJob,
  deleteMaterialProfile,
  deletePrinter,
  deleteSettingsProfile,
  downloadModelFile,
  duplicateMaterialProfile,
  duplicateSettingsProfile,
  getJob,
  getModelPlates,
  orientModel,
  transformModel,
  transformObjects,
  getProfileDetail,
  getSettingsSchema,
  listImportedProfiles,
  listJobs,
  listMaterialProfiles,
  listPrinters,
  listProfiles,
  listSampleModels,
  listSettingsProfiles,
  loadSampleModel,
  sendToPrinter,
  updateMaterialProfile,
  updatePrinter,
  updateSettingsProfile,
  uploadModel,
} from './api'
import {
  type BedSize,
  type Dimensions,
  computeFitScale,
  parseBedSize,
  scaleStlFile,
  canScaleFile,
  SCALE_UNSUPPORTED_MESSAGE,
} from './dimensions'
import type { BeltTransform } from './beltTransform'
import AdvancedSettings from './components/AdvancedSettings'
import FilamentSelect from './components/FilamentSelect'
import MaterialDialog from './components/MaterialDialog'
import RotateMoveDialog from './components/RotateMoveDialog'
import GcodeViewer from './components/GcodeViewer'
import JobPanel from './components/JobPanel'
import LoginGate from './components/LoginGate'
import CopiesControl from './components/CopiesControl'
import ObjectPicker from './components/ObjectPicker'
import { beltRowShifts, type RowMode } from './beltLayout'
import PlatePicker from './components/PlatePicker'
import PositionPanel from './components/PositionPanel'
import ProfileImportDialog from './components/ProfileImportDialog'
import PrinterDialog from './components/PrinterDialog'
import ExportDialog from './components/ExportDialog'
import PrinterSelect from './components/PrinterSelect'
import QuickSettings, {
  BELT_BRIM_TYPES,
  QUICK_SETTING_KEYS,
  defaultQuickSettings,
  type QuickSettingsValues,
} from './components/QuickSettings'
import SavedPrinters from './components/SavedPrinters'
import SavedProfilePicker from './components/SavedProfilePicker'
import ScaleControls from './components/ScaleControls'
import SendToPrinterControl from './components/SendToPrinterControl'
import SettingsMenu from './components/SettingsMenu'
import SetupGate from './components/SetupGate'
import Uploader from './components/Uploader'
import Viewer, { type ViewerHandle } from './components/Viewer'
import type {
  ColorNode,
  JobRecord,
  MaterialProfileRecord,
  MeshReport,
  ObjectInfo,
  Placement,
  PrinterConnection,
  PrinterRecord,
  PrinterUpdateRequest,
  ProfileSummary,
  SampleModelSummary,
  SettingDef,
  SettingsProfileRecord,
  ThreeMfInspection,
  ObjectEdit,
  TransformStep,
} from './types'
import { pickBedType, supportedBedTypes } from './bedTypes'
import { useAuth } from './useAuth'

const ACTIVE_STATUSES: JobRecord['status'][] = ['queued', 'running']
const POLL_INTERVAL_MS = 1500

// A stable fingerprint of everything that actually affects slice output.
// Used to tell "you changed something" apart from "you clicked Slice again
// with the same settings" -- object key order isn't guaranteed to stay
// consistent across state updates, so each object's entries are sorted by
// key before stringifying rather than relying on JSON.stringify's
// insertion-order behavior.
function sortedEntries(obj: Record<string, unknown>): [string, unknown][] {
  return Object.keys(obj)
    .sort()
    .map((key) => [key, obj[key]])
}

// api/app/gcode_stats.py adds this to a succeeded job's own result blob
// (OrcaSlicer's own result.json never carries it) -- null for any other
// status, or a job whose gcode footer didn't have a parseable line.
function filamentGramsOf(job: JobRecord | null): number | null {
  if (job?.status !== 'succeeded') return null
  const grams = job.result?.filament_used_g
  return typeof grams === 'number' ? grams : null
}

function computeSliceSignature(
  modelId: string | null,
  printerName: string,
  processName: string,
  effectiveFilamentProfiles: string[],
  plateIndex: number | null,
  quickSettings: QuickSettingsValues,
  advancedOverrides: Record<string, string>,
  nozzleSettingsSignature: string,
  // Which objects of a multi-object file are printed, and (belt) how they
  // are laid out -- see objectSelectionSignature below.
  objectSelectionSignature: string,
  // Two different physical-slot assignments can resolve to the identical
  // effectiveFilamentProfiles array whenever the slots involved share a
  // material profile (exactly the case that caused a real print to come
  // out the wrong colors: two slots both set to the same PLA, so which
  // physical head prints which role never showed up in the signature at
  // all) -- include the raw per-role slot assignment directly so changing
  // it always counts as "you changed something," even then.
  roleNozzleAssignments: (number | null)[],
): string {
  return JSON.stringify({
    modelId,
    printerName,
    processName,
    effectiveFilamentProfiles,
    plateIndex,
    quickSettings: sortedEntries(quickSettings as unknown as Record<string, unknown>),
    advancedOverrides: sortedEntries(advancedOverrides),
    nozzleSettingsSignature,
    objectSelectionSignature,
    roleNozzleAssignments,
  })
}

interface FilamentSlot {
  profile: string
  color: string
  // OrcaSlicer models both as per-extruder-variant settings (confirmed:
  // vendor/orcaslicer/src/libslic3r/PrintConfig.cpp defines nozzle_type as
  // an array indexed by extruder, same as nozzle_diameter). Only exposed
  // per-slot in the UI for a genuine multi-head printer -- a single-nozzle
  // printer (AMS-style) uses one shared globalNozzleDiameter/globalNozzleType
  // instead, since every slot feeds the same physical hotend.
  nozzleDiameter: number
  nozzleType: string
}

// A printer's multi-material/AMS capability can go well past what any one
// bundled catalog profile happens to define -- the user explicitly wants to
// start from whatever printer/process profile fits their machine's process
// settings and manually dial in however many physical heads/AMS slots they
// actually have, rather than being limited to (or having to work around a
// mismatch with) a specific catalog SKU's assumed head count.
const MAX_FILAMENT_SLOTS = 16

const NOZZLE_TYPE_LABELS: Record<string, string> = {
  undefine: 'Unspecified',
  hardened_steel: 'Hardened steel',
  stainless_steel: 'Stainless steel',
  tungsten_carbide: 'Tungsten carbide',
  brass: 'Brass',
}
const FALLBACK_NOZZLE_TYPES = Object.keys(NOZZLE_TYPE_LABELS)

function nozzleTypeLabel(value: string): string {
  return NOZZLE_TYPE_LABELS[value] ?? value
}

// Cycled by index when a fresh slot is added (picking a printer with more
// heads/AMS slots than the previous one, or a brand-new upload) so slots
// aren't all identically colored -- purely a UI label, never sent to
// OrcaSlicer.
// Matches entries in COLOR_PRESETS below exactly (not just visually similar
// hex values) so a freshly-added slot's default color always has a
// friendly name available in the nozzle-assignment dropdown, rather than
// falling back to a raw hex code there.
const DEFAULT_SLOT_COLORS = ['#ffffff', '#e0301e', '#0a84ff', '#ffd60a', '#34c759', '#af52de']

function defaultSlotColor(index: number): string {
  return DEFAULT_SLOT_COLORS[index % DEFAULT_SLOT_COLORS.length]
}

// One-click presets covering the filament colors people actually load
// (black/white/gray included -- notably absent from DEFAULT_SLOT_COLORS
// above, which only needs to be *distinct* per slot, not comprehensive).
// The native <input type="color"> below still covers anything else. Named
// (not just hex) so a plain-text context that can't render a swatch --
// e.g. a <select><option> in the nozzle-assignment dropdown, which has no
// way to show a colored box -- can still say "Red" instead of "#e0301e".
const COLOR_PRESETS = [
  { hex: '#000000', name: 'Black' },
  { hex: '#ffffff', name: 'White' },
  { hex: '#808080', name: 'Gray' },
  { hex: '#e0301e', name: 'Red' },
  { hex: '#ff8c00', name: 'Orange' },
  { hex: '#ffd60a', name: 'Yellow' },
  { hex: '#34c759', name: 'Green' },
  { hex: '#00c2d1', name: 'Teal' },
  { hex: '#0a84ff', name: 'Blue' },
  { hex: '#af52de', name: 'Purple' },
  { hex: '#ff2d92', name: 'Pink' },
  { hex: '#8b5a2b', name: 'Brown' },
]

const COLOR_NAME_BY_HEX = new Map(COLOR_PRESETS.map(({ hex, name }) => [hex.toLowerCase(), name]))

// Falls back to the raw hex for a custom color picked via the native
// dialog rather than one of the presets above -- still better than no
// label at all when matching a slot to a file's saved color/name.
function colorLabel(hex: string): string {
  return COLOR_NAME_BY_HEX.get(hex.toLowerCase()) ?? hex
}

// One slot per physical extruder/AMS slot -- the user controls the count
// directly (starts at 1, "+"/"-" in the Material section; see
// addFilamentSlot/removeFilamentSlot below) rather than it being derived
// from the selected machine profile. nozzleDiameters/nozzleTypes (the
// catalog's own per-extruder-variant values, when known) just seed sensible
// defaults for freshly-built slots -- the user can edit any of it per slot.
function buildFilamentSlots(
  count: number,
  defaultProfile: string,
  nozzleDiameters: number[] = [],
  nozzleTypes: string[] = [],
): FilamentSlot[] {
  return Array.from({ length: Math.max(1, count) }, (_, i) => ({
    profile: defaultProfile,
    color: defaultSlotColor(i),
    nozzleDiameter: nozzleDiameters[i] ?? nozzleDiameters[nozzleDiameters.length - 1] ?? 0.4,
    nozzleType: nozzleTypes[i] ?? nozzleTypes[nozzleTypes.length - 1] ?? 'undefine',
  }))
}

// Confirmed via direct CLI testing against a real toolchanger printer
// (Snapmaker U1 0.4+0.6 nozzle): its own bundled process profile's default
// bridge_line_width exceeds 0.6mm-nozzle validation ("Bridge line width
// must not exceed nozzle diameter: 0.600000"), failing *every* slice
// against that machine regardless of which physical nozzle is actually
// used -- a pre-existing bug in the catalog's own data, not anything to
// do with which materials/nozzle a job picks. Clamping to the smallest
// configured nozzle whenever a machine mixes diameters sidesteps it.
function parsedNozzleDiameters(data: Record<string, unknown> | undefined): number[] {
  const raw = data?.nozzle_diameter
  if (!Array.isArray(raw)) return []
  return raw.map((v) => Number(v)).filter((n) => Number.isFinite(n) && n > 0)
}

// A catalog leaf sometimes writes this as a single string rather than an
// array when every nozzle is the same type (confirmed: Snapmaker U1's own
// leaf profiles do this, unlike their nozzle_diameter, which is always a
// real per-slot array) -- broadcast a bare string as a one-element array so
// buildFilamentSlots' "repeat the last value" fallback still seeds every
// slot with it correctly.
function parsedNozzleTypes(data: Record<string, unknown> | undefined): string[] {
  const raw = data?.nozzle_type
  if (Array.isArray(raw)) return raw.map((v) => String(v))
  if (typeof raw === 'string' && raw) return [raw]
  return []
}

// One entry per filament role the uploaded file itself needs -- e.g. a
// plain STL is always exactly one anonymous role, a 2-color painted 3mf
// is two roles with real original colors. `color` is the file's own
// author's color for that role when known (from Metadata/project_settings
// .config's filament_colour, which catches paint-on/per-triangle color
// assignments that per-object extruder metadata misses entirely -- see
// api/app/threemf.py) -- null when genuinely unknown. `name` is that same
// file's saved material name for the role (e.g. "Bambu PLA Basic @BBL
// A1M") when known -- shown purely to help matching it to one of your own
// materials, never treated as an actual profile in your own catalog.
interface FileRole {
  color: string | null
  name: string | null
}

function fileRolesFromInspection(info: ThreeMfInspection | null): FileRole[] {
  if (info?.embedded_filament_colors.length) {
    return info.embedded_filament_colors.map((c, i) => ({
      color: c || null,
      name: info.embedded_filament_names[i] || null,
    }))
  }
  const count = info?.extruder_indices.length || 1
  return Array.from({ length: count }, () => ({ color: null, name: null }))
}

// Where your own (imported or created) profiles live (api/app/userprofiles.py).
const IMPORTED_VENDOR = 'My profiles'

export default function App() {
  const auth = useAuth()

  if (!auth.status) return null // brief first-load flash while /auth/status resolves

  if (auth.status.mode === 'unset') {
    return (
      <SetupGate
        onChooseSingle={() => auth.setup({ mode: 'single' })}
        onChooseMulti={(username, password) => auth.setup({ mode: 'multi', username, password })}
      />
    )
  }

  if (auth.status.mode === 'multi' && !auth.status.logged_in) {
    return <LoginGate onLogin={auth.login} />
  }

  return (
    <MainApp
      authStatus={auth.status}
      onSwitchToMulti={auth.switchToMulti}
      onSwitchToSingle={auth.switchToSingle}
      onCreateUser={auth.createUser}
      onLogout={auth.logout}
      onUpdateLastSelection={auth.updateLastSelection}
    />
  )
}

interface MainAppProps {
  authStatus: NonNullable<ReturnType<typeof useAuth>['status']>
  onSwitchToMulti: (username: string, password: string) => Promise<unknown>
  onSwitchToSingle: () => Promise<unknown>
  onCreateUser: (username: string, password: string) => Promise<unknown>
  onLogout: () => Promise<unknown>
  onUpdateLastSelection: (
    printerId: string | null,
    materialId: string | null,
    settingsProfileId: string | null,
  ) => Promise<unknown>
}

function MainApp({
  authStatus,
  onSwitchToMulti,
  onSwitchToSingle,
  onCreateUser,
  onLogout,
  onUpdateLastSelection,
}: MainAppProps) {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([])
  const [importOpen, setImportOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  // The "New printer" / "Edit printer" form, and a printer just saved that is to be selected once the list has it.
  const [printerDialog, setPrinterDialog] = useState<{ mode: 'create' | 'edit' } | null>(null)
  const [pendingPrinter, setPendingPrinter] = useState<string | null>(null)
  // The "Rotate and move" window (RotateMoveDialog).
  const [rotateMoveOpen, setRotateMoveOpen] = useState(false)
  // The "New material" / "Edit material" form, opened from a material slot.
  const [materialDialog, setMaterialDialog] = useState<{
    mode: 'create' | 'edit'
    slot: number
    base: { vendor: string; name: string }
  } | null>(null)
  // Build plates the selected material(s) can print on (null = no restriction
  // known), and the printer's own default plate.
  const [allowedBedTypes, setAllowedBedTypes] = useState<string[] | null>(null)
  const [printerDefaultBed, setPrinterDefaultBed] = useState<string | null>(null)
  // Where the user put the model on the plate (Position panel); null = the
  // slicer's own default spot.
  const [placement, setPlacement] = useState<Placement | null>(null)
  // How many copies of the (selected) model to print.
  const [copies, setCopies] = useState(1)
  // The job whose "line them up instead?" question was already answered, and
  // whether to slice again as soon as line-up is switched on.
  const [lineUpAnsweredFor, setLineUpAnsweredFor] = useState<string | null>(null)
  const [retryAfterLineUp, setRetryAfterLineUp] = useState(false)
  const [positionBusy, setPositionBusy] = useState<'orient' | 'arrange' | null>(null)
  const [schema, setSchema] = useState<SettingDef[]>([])
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [sampleModels, setSampleModels] = useState<SampleModelSummary[]>([])

  const [file, setFile] = useState<File | null>(null)
  const [modelId, setModelId] = useState<string | null>(null)
  const [uploadStatus, setUploadStatus] = useState<'idle' | 'uploading' | 'done' | 'error'>('idle')
  const [dimensions, setDimensions] = useState<Dimensions | null>(null)

  const [vendor, setVendor] = useState('')
  const [printerName, setPrinterName] = useState('')
  const [processName, setProcessName] = useState('')
  const [filamentSlots, setFilamentSlots] = useState<FilamentSlot[]>(buildFilamentSlots(1, ''))
  const [bedSize, setBedSize] = useState<BedSize | null>(null)
  // The selected machine's own nozzle_diameter/nozzle_type values (see
  // parsedNozzleDiameters/parsedNozzleTypes above) -- used only to seed
  // sensible defaults (freshly built/added slots, the global control below)
  // and to clamp bridge_line_width; never sent to OrcaSlicer directly.
  const [nozzleDiameters, setNozzleDiameters] = useState<number[]>([])
  const [nozzleTypes, setNozzleTypes] = useState<string[]>([])
  const [globalNozzleDiameter, setGlobalNozzleDiameter] = useState('')
  const [globalNozzleType, setGlobalNozzleType] = useState('undefine')

  // Premade multi-plate/multi-material .3mf support: parsed once per upload
  // (see handleFileSelected), always present (a synthetic single implicit
  // plate for non-3mf uploads) so the plate picker/nozzle-assignment UI
  // below can render unconditionally off its shape.
  const [plateInfo, setPlateInfo] = useState<ThreeMfInspection | null>(null)
  const [plateIndex, setPlateIndex] = useState<number | null>(null)
  // Which objects of a multi-object .3mf to leave out of the print, and how
  // a belt printer lines the rest up (ObjectPicker). Indices are
  // ObjectInfo.index, i.e. build-item order.
  const [excludedObjects, setExcludedObjects] = useState<Set<number>>(new Set())
  const [beltLineUp, setBeltLineUp] = useState(true)
  const [beltOrder, setBeltOrder] = useState<number[]>([])
  const [beltGapMm, setBeltGapMm] = useState(10)
  // A multi-plate file on a belt printer: each plate as a block one after another (the default), or every object in one row.
  const [beltRowMode, setBeltRowMode] = useState<RowMode>('plates')
  const [objectThumbs, setObjectThumbs] = useState<Record<number, string>>({})
  const [objectPickerOpen, setObjectPickerOpen] = useState(false)
  // Result of the upload-time STL check, and whether its notice was dismissed.
  const [meshReport, setMeshReport] = useState<MeshReport | null>(null)
  const [meshToastDismissed, setMeshToastDismissed] = useState(false)
  // A newly loaded file starts with everything selected, in file order.
  useEffect(() => {
    setExcludedObjects(new Set())
    setBeltRowMode('plates')
    // Plate by plate (then file order within a plate), so a multi-plate file goes along the belt plate 1, 2, 3.
    setBeltOrder([...(plateInfo?.objects ?? [])].sort((a, b) => a.plate - b.plate || a.index - b.index).map((o) => o.index))
  }, [plateInfo])
  // Which of the printer's configured filamentSlots (by index) supplies
  // each "role" (color/material) the uploaded file itself needs -- see
  // fileRoles below. null means "not chosen yet". Sending a mismatched
  // filament count relative to what the file actually needs (previously:
  // always all of filamentSlots, regardless of file need) is a confirmed
  // OrcaSlicer CLI crash trigger (exit code -11) against a real downloaded
  // multi-color model whose file only needed 2 roles but got 4 filaments
  // -- this explicit per-role mapping is what keeps the sent count exactly
  // matching what the file needs, chosen from real catalog-backed slots.
  const [roleNozzleAssignments, setRoleNozzleAssignments] = useState<(number | null)[]>([0])

  const [scaleToastDismissed, setScaleToastDismissed] = useState(false)
  const [scaling, setScaling] = useState(false)

  const [printers, setPrinters] = useState<PrinterRecord[]>([])
  const [selectedPrinterId, setSelectedPrinterId] = useState<string | null>(null)
  const [materials, setMaterials] = useState<MaterialProfileRecord[]>([])
  const [selectedMaterialId, setSelectedMaterialId] = useState<string | null>(null)
  // Independent from materials -- see SettingsProfileRecord: print-quality
  // settings only, saved/loaded separately so the same materials can be
  // reused across quality presets and vice versa.
  const [settingsProfiles, setSettingsProfiles] = useState<SettingsProfileRecord[]>([])
  const [selectedSettingsProfileId, setSelectedSettingsProfileId] = useState<string | null>(null)

  // Restoring the account's last-selected printer/material/settings profile
  // (see the mount and material-/settings-list effects below) is an async,
  // two-step process -- printers load first, then (if a printer was
  // restored) its materials and settings profiles, in parallel.
  // `restorationDone`/`settingsRestorationDone` gate the persist-on-change
  // effect further down so it can't fire with a half-restored state
  // (printer set, material/settings profile still null) and overwrite the
  // correct persisted id with null before that second step finishes.
  // `pendingLastMaterialId`/`pendingLastSettingsProfileId` are each
  // consumed exactly once -- only meaningful for that first, restored
  // fetch, not any later manual printer switch.
  const [restorationDone, setRestorationDone] = useState(false)
  const [settingsRestorationDone, setSettingsRestorationDone] = useState(false)
  const [printersLoaded, setPrintersLoaded] = useState(false)
  const pendingLastMaterialId = useRef(authStatus.last_material_id)
  const pendingLastSettingsProfileId = useRef(authStatus.last_settings_profile_id)
  // Set once (never reset) the first time a real saved settings profile's
  // values are actually applied -- guards the initial-catalog-load effect
  // below against a genuine race: that effect and the printer/settings-
  // profile restoration chain (auth status -> printers -> saved printer's
  // settings profiles -> apply) both kick off independently from mount, in
  // no guaranteed order. Confirmed via real testing: the settings-profile
  // dropdown correctly showed the restored profile's name, but its actual
  // quick-setting values (e.g. enable_support) were silently reset to bare
  // schema defaults -- the catalog-load effect's own setQuickSettings had
  // resolved AFTER the profile's real values were already applied, clobbering
  // them. This ref makes the outcome correct regardless of which finishes
  // first, unlike checking pendingLastSettingsProfileId alone (which is only
  // reliable for one specific ordering).
  const appliedSettingsProfileRef = useRef(false)
  // Lets handleSlice grab a snapshot of the 3D preview at the moment
  // slicing starts, to embed into the gcode and this app's own job
  // thumbnail (see api/app/gcode_thumbnail.py) -- the engine itself never
  // renders one in CLI mode.
  const viewerRef = useRef<ViewerHandle>(null)

  const [quickSettings, setQuickSettings] = useState<QuickSettingsValues>(defaultQuickSettings([]))
  const [advancedOverrides, setAdvancedOverrides] = useState<Record<string, string>>({})

  // A color change can only happen at all once there's more than one
  // filament slot configured on the printer (whether that's several heads
  // or several AMS-style slots feeding one shared nozzle) -- crossing that
  // threshold turns the prime/wipe tower on by default, since leftover
  // filament on the nozzle from the previous color would otherwise show up
  // in the next layer. Deliberately keyed on the true/false threshold
  // itself, not the raw slot count, so it fires once going from a single
  // material to several, not on every subsequent slot added/removed while
  // already multi-material -- the checkbox in QuickSettings stays a normal
  // toggle either way, this is just the starting point.
  //
  // Never for a belt printer: fdm_belt_common.json sets
  // purge_in_prime_tower=0 and belt mode has its own dedicated
  // purge-into-object system (BeltPurge.cpp/Print::has_belt_purge_tower(),
  // replacing the classic wipe tower) that a forced classic prime tower
  // would conflict with. Multi-extruder belt printers are essentially
  // nonexistent in practice, so this only ever skips a default that would
  // otherwise never even apply.
  const hasMultipleFilamentSlots = filamentSlots.length > 1 && !bedSize?.beltPrinterInfiniteY
  useEffect(() => {
    if (hasMultipleFilamentSlots) {
      setQuickSettings((prev) => (prev.enable_prime_tower === '1' ? prev : { ...prev, enable_prime_tower: '1' }))
    }
  }, [hasMultipleFilamentSlots])

  const [slicing, setSlicing] = useState(false)
  const [currentJob, setCurrentJob] = useState<JobRecord | null>(null)
  const [history, setHistory] = useState<JobRecord[]>([])
  // Signature of the settings the current/last job was actually sliced
  // with, so a repeat click of "Slice" with nothing changed can be a no-op
  // instead of queuing an identical job.
  const [lastSlicedSignature, setLastSlicedSignature] = useState<string | null>(null)

  // Which job's G-code the viewer panel shows, and whether it's showing
  // that at all right now (vs. the 3D model). Separate from currentJob:
  // a history item can be previewed independently of whatever's currently
  // slicing.
  const [viewedJobId, setViewedJobId] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'model' | 'gcode'>('model')

  const showGcode = viewMode === 'gcode' && viewedJobId !== null

  // The gcode viewer's belt back-transform (see beltTransform.ts) must match
  // whichever printer THIS job was actually sliced with, not whatever the
  // printer dropdown currently has selected (`bedSize` below) -- those two
  // can disagree the moment a job from history is reopened, or the page
  // reloads, without reselecting the same printer. Resolved independently
  // here from the job's own recorded printer_profile so the viewer is
  // correct regardless of ambient UI selection state.
  const [viewedJobBeltTransform, setViewedJobBeltTransform] = useState<BeltTransform | null>(null)
  useEffect(() => {
    const job = viewedJobId ? ([currentJob, ...history].find((j) => j?.id === viewedJobId) ?? null) : null
    if (!job) {
      setViewedJobBeltTransform(null)
      return
    }
    let cancelled = false
    listProfiles()
      .then((profiles) => {
        const match = profiles.find((p) => p.kind === 'machine' && p.name === job.printer_profile)
        return match ? getProfileDetail(match.vendor, 'machine', match.name) : null
      })
      .then((detail) => {
        if (cancelled) return
        setViewedJobBeltTransform(detail ? (parseBedSize(detail.data)?.beltTransform ?? null) : null)
      })
      .catch(() => {
        if (!cancelled) setViewedJobBeltTransform(null)
      })
    return () => {
      cancelled = true
    }
  }, [viewedJobId, currentJob, history])

  const viewJobGcode = useCallback((jobId: string) => {
    setViewedJobId(jobId)
    setViewMode('gcode')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])

  const backToModelView = useCallback(() => setViewMode('model'), [])

  const selectedPrinter = printers.find((p) => p.id === selectedPrinterId) ?? null
  const selectedMaterial = materials.find((m) => m.id === selectedMaterialId) ?? null
  const selectedSettingsProfile = settingsProfiles.find((p) => p.id === selectedSettingsProfileId) ?? null

  // Whether this machine has multiple independent physical nozzles/heads,
  // each of which can carry a different size/type (a genuine toolchanger,
  // e.g. Snapmaker U1) vs. one shared nozzle feeding every material slot
  // (AMS-style, e.g. Bambu X1C) -- derived from nozzle_diameter's own array
  // length, the one per-extruder-variant field every catalog machine leaf
  // profile reliably sets directly. Deliberately NOT derived from
  // single_extruder_multi_material: that field is typically only set on a
  // shared ancestor template (confirmed: neither Snapmaker U1 variant nor
  // most Bambu machines set it on their own leaf file), and this backend
  // never flattens `inherits` chains (see api/app/profiles.py) -- so it's
  // absent from detail.data for almost every real machine, which would
  // silently default every printer to "single nozzle" and break the exact
  // multi-head case this control exists for.
  const isMultiHeadPrinter = nozzleDiameters.length > 1

  // Collapsed by default once a saved printer/material/settings profile is
  // actually picked (nothing left to configure), expanded otherwise. Only
  // *changes* to the selection force the collapse state -- toggling the
  // <details> manually afterward (e.g. to peek at or tweak a selected
  // profile) sticks until the selection changes again, rather than
  // snapping back on every render.
  const [printerSettingsOpen, setPrinterSettingsOpen] = useState(!selectedPrinterId)
  const [materialSectionOpen, setMaterialSectionOpen] = useState(!selectedMaterialId)
  const [settingsSectionOpen, setSettingsSectionOpen] = useState(!selectedSettingsProfileId)
  useEffect(() => setPrinterSettingsOpen(!selectedPrinterId), [selectedPrinterId])
  useEffect(() => setMaterialSectionOpen(!selectedMaterialId), [selectedMaterialId])
  useEffect(() => setSettingsSectionOpen(!selectedSettingsProfileId), [selectedSettingsProfileId])

  const handleSendToPrinter = useCallback(
    (jobId: string, startPrint: boolean) => {
      if (!selectedPrinterId) return Promise.reject(new Error('No printer selected'))
      return sendToPrinter(selectedPrinterId, jobId, startPrint)
    },
    [selectedPrinterId],
  )

  const handleDeleteJob = useCallback(
    (jobId: string) => {
      deleteJob(jobId)
        .then(() => {
          listJobs().then(setHistory).catch(() => {})
          setCurrentJob((prev) => (prev?.id === jobId ? null : prev))
          setViewedJobId((prev) => {
            if (prev !== jobId) return prev
            setViewMode('model')
            return null
          })
        })
        .catch((err: Error) => alert(`Failed to delete job: ${err.message}`))
    },
    [],
  )

  // Initial catalog load.
  useEffect(() => {
    Promise.all([listProfiles(), getSettingsSchema()])
      .then(([profileList, settingsSchema]) => {
        setProfiles(profileList)
        setSchema(settingsSchema.settings)
        // Skip if a real saved settings profile's values already won the
        // race (see appliedSettingsProfileRef above) -- this would otherwise
        // unconditionally stomp them back to bare defaults.
        if (!appliedSettingsProfileRef.current) {
          setQuickSettings(defaultQuickSettings(settingsSchema.settings))
        }
      })
      .catch((err: Error) => setCatalogError(err.message))

    listJobs()
      .then(setHistory)
      .catch(() => {
        /* history is a nice-to-have; ignore failures */
      })

    listPrinters()
      .then((list) => {
        setPrinters(list)
        setPrintersLoaded(true)
      })
      .catch(() => setPrintersLoaded(true))

    listSampleModels()
      .then(setSampleModels)
      .catch(() => {
        /* the settings menu's sample-model list is a nice-to-have; ignore failures */
      })
  }, [])

  // Read via refs (not state) inside applyMaterialProfile below, so that
  // callback's identity stays stable regardless of when the catalog's own
  // nozzle data happens to arrive -- applySavedPrinter fetches it
  // asynchronously *after* already setting selectedPrinterId, and this
  // callback's identity is itself a dependency of the materials-fetch
  // effect further down; if it changed later (state instead of a ref), that
  // effect would re-fire, refetch materials, and wipe out a just-restored
  // material selection out from under the user.
  const nozzleDiametersRef = useRef<number[]>([])
  const nozzleTypesRef = useRef<string[]>([])
  useEffect(() => {
    nozzleDiametersRef.current = nozzleDiameters
  }, [nozzleDiameters])
  useEffect(() => {
    nozzleTypesRef.current = nozzleTypes
  }, [nozzleTypes])

  const applyMaterialProfile = useCallback((material: MaterialProfileRecord) => {
    setSelectedMaterialId(material.id)
    if (material.filament_profiles && material.filament_profiles.length > 0) {
      // A material profile doesn't save nozzle diameter/type (those are a
      // property of the physical printer/head, not the material) -- keep
      // whatever's already dialed in per slot where possible, falling back
      // to the catalog's own defaults for any newly-appearing slot.
      const diameters = nozzleDiametersRef.current
      const types = nozzleTypesRef.current
      setFilamentSlots((prev) =>
        material.filament_profiles!.map((profile, i) => ({
          profile,
          color: material.filament_colors?.[i] ?? defaultSlotColor(i),
          nozzleDiameter: prev[i]?.nozzleDiameter ?? diameters[i] ?? diameters[diameters.length - 1] ?? 0.4,
          nozzleType: prev[i]?.nozzleType ?? types[i] ?? types[types.length - 1] ?? 'undefine',
        })),
      )
    }
    setViewMode('model')
  }, [])

  const applySettingsProfile = useCallback((profile: SettingsProfileRecord) => {
    appliedSettingsProfileRef.current = true
    setSelectedSettingsProfileId(profile.id)
    setQuickSettings((prev) => ({ ...prev, ...profile.quick_settings }))
    setAdvancedOverrides(profile.advanced_overrides)
    if (profile.process_profile) setProcessName(profile.process_profile)
    setViewMode('model')
  }, [])

  // A saved printer's material profiles only matter while that printer is
  // selected -- reload (and drop any stale selection) whenever it changes.
  useEffect(() => {
    if (!selectedPrinterId) {
      setMaterials([])
      setSelectedMaterialId(null)
      return
    }
    setSelectedMaterialId(null)
    listMaterialProfiles(selectedPrinterId)
      .then((list) => {
        setMaterials(list)
        // Only ever meaningful for the one materials fetch that follows a
        // restored printer selection (below) -- consumed once so a later,
        // manual printer switch doesn't try to reapply a stale id.
        const pendingId = pendingLastMaterialId.current
        pendingLastMaterialId.current = null
        const match = pendingId ? list.find((m) => m.id === pendingId) : undefined
        if (match) applyMaterialProfile(match)
      })
      .catch(() => setMaterials([]))
      .finally(() => setRestorationDone(true))
  }, [selectedPrinterId, applyMaterialProfile])

  // Same idea for settings profiles, restored independently of materials
  // (a different id in AuthStatus, applied via its own pending ref).
  useEffect(() => {
    if (!selectedPrinterId) {
      setSettingsProfiles([])
      setSelectedSettingsProfileId(null)
      return
    }
    setSelectedSettingsProfileId(null)
    listSettingsProfiles(selectedPrinterId)
      .then((list) => {
        setSettingsProfiles(list)
        const pendingId = pendingLastSettingsProfileId.current
        pendingLastSettingsProfileId.current = null
        const match = pendingId ? list.find((p) => p.id === pendingId) : undefined
        if (match) applySettingsProfile(match)
      })
      .catch(() => setSettingsProfiles([]))
      .finally(() => setSettingsRestorationDone(true))
  }, [selectedPrinterId, applySettingsProfile])

  // A multi-plate file opens on its first plate, like OrcaSlicer: the preview
  // shows that plate, and the picker can switch it.
  const applyInspection = useCallback((inspection: ThreeMfInspection) => {
    setPlateInfo(inspection)
    setPlateIndex(inspection.plates.length > 1 ? inspection.plates[0].index : null)
  }, [])

  const handleFileSelected = useCallback((selected: File) => {
    setFile(selected)
    setModelId(null)
    setUploadStatus('uploading')
    setScaleToastDismissed(false)
    setViewMode('model')
    setPlateInfo(null)
    setPlateIndex(null)
    setObjectThumbs({})
    setObjectPickerOpen(false)
    setPlacement(null)
    setCopies(1)
    setMeshReport(null)
    setMeshToastDismissed(false)
    uploadModel(selected)
      .then((res) => {
        setMeshReport(res.mesh_report ?? null)
        setModelId(res.model_id)
        setUploadStatus('done')
        // Always fetch (even for non-3mf uploads): the endpoint always
        // returns a shape (a synthetic single implicit plate for anything
        // that isn't a .3mf with real plate metadata), so the plate
        // picker/nozzle-assignment UI never need a separate "is this even
        // a 3mf" branch.
        getModelPlates(res.model_id)
          .then(applyInspection)
          .catch(() => setPlateInfo(null))
      })
      .catch(() => setUploadStatus('error'))
  }, [applyInspection])

  // Auto-orient / Auto-arrange: the slicer's own helpers run server-side and
  // produce a new .3mf, which replaces the loaded model. After an arrange the
  // sliders show where it put the model; after an orient the position goes
  // back to the slicer's default.
  const runModelOp = useCallback(
    (op: 'orient' | 'arrange') => {
      if (!modelId || !printerName || !processName) return
      setPositionBusy(op)
      const request =
        op === 'orient' ? orientModel(modelId, printerName, processName) : arrangeModel(modelId, printerName, processName)
      request
        .then(async (res) => {
          const [downloaded, inspection] = await Promise.all([downloadModelFile(res.model_id), getModelPlates(res.model_id)])
          applyInspection(inspection)
          setFile(downloaded)
          setModelId(res.model_id)
          setViewMode('model')
          const objs = inspection.objects ?? []
          if (op === 'arrange' && objs.length > 0) {
            const minX = Math.min(...objs.map((o) => o.center_x_mm - o.width_mm / 2))
            const maxX = Math.max(...objs.map((o) => o.center_x_mm + o.width_mm / 2))
            const minY = Math.min(...objs.map((o) => o.center_y_mm - o.depth_mm / 2))
            const maxY = Math.max(...objs.map((o) => o.center_y_mm + o.depth_mm / 2))
            setPlacement({ x: (minX + maxX) / 2, y: (minY + maxY) / 2 })
          } else {
            setPlacement(null)
          }
        })
        .catch((err: Error) => alert(`Could not ${op === 'orient' ? 'orient' : 'arrange'} the model: ${err.message}`))
        .finally(() => setPositionBusy(null))
    },
    [modelId, printerName, processName, applyInspection],
  )

  // Rotate / stand the model on a face with the slicer (RotateMoveDialog), swap the
  // result in the way auto-orient does, and keep the position the user chose.
  const handleTransformModel = useCallback(
    async (steps: TransformStep[], position: Placement): Promise<boolean> => {
      if (!modelId) return false
      try {
        const res = await transformModel(modelId, steps)
        const [downloaded, inspection] = await Promise.all([downloadModelFile(res.model_id), getModelPlates(res.model_id)])
        applyInspection(inspection)
        setFile(downloaded)
        setModelId(res.model_id)
        setViewMode('model')
        setPlacement(position)
        return true
      } catch (err) {
        alert(`Could not turn the model: ${(err as Error).message}`)
        return false
      }
    },
    [modelId, applyInspection],
  )

  // Turn and move the objects of a multi-object file one by one (RotateMoveDialog). The new model
  // keeps each object where it was put, so the group's centre is read back from it.
  const handleTransformObjects = useCallback(
    async (edits: ObjectEdit[], groupCentre: Placement): Promise<boolean> => {
      if (!modelId) return false
      try {
        const res = await transformObjects(modelId, edits)
        const [downloaded, inspection] = await Promise.all([downloadModelFile(res.model_id), getModelPlates(res.model_id)])
        applyInspection(inspection)
        // applyInspection goes back to the first plate; the user is still working on this one.
        if (inspection.plates.length > 1 && inspection.plates.some((p) => p.index === plateIndex)) setPlateIndex(plateIndex)
        setFile(downloaded)
        setModelId(res.model_id)
        setViewMode('model')
        const listed = inspection.objects ?? []
        if (inspection.plates.length > 1) {
          // Plates keep the file's own coordinates; there is no group position to keep.
        } else if (listed.length > 0) {
          // Measured the way the server measures it when it places the group, so the job moves nothing.
          const minX = Math.min(...listed.map((o) => o.center_x_mm - o.width_mm / 2))
          const maxX = Math.max(...listed.map((o) => o.center_x_mm + o.width_mm / 2))
          const minY = Math.min(...listed.map((o) => o.center_y_mm - o.depth_mm / 2))
          const maxY = Math.max(...listed.map((o) => o.center_y_mm + o.depth_mm / 2))
          setPlacement({ x: (minX + maxX) / 2, y: (minY + maxY) / 2 })
        } else {
          setPlacement(groupCentre)
        }
        return true
      } catch (err) {
        alert(`Could not turn the objects: ${(err as Error).message}`)
        return false
      }
    },
    [modelId, applyInspection, plateIndex],
  )

  // Loads one of the built-in sample models (SettingsMenu's "Load a sample
  // model…") instead of a local upload. The model is created server-side
  // (routers/sample_models.py copies the bundled file into a fresh
  // model_id), so unlike handleFileSelected there's no File object already
  // in hand -- re-fetch the bytes into one via GET /models/{id}/file so the
  // rest of the app (viewer preview, scale-to-fit) works exactly the same
  // as it does for a local upload.
  const handleLoadSample = useCallback((sampleId: string) => {
    setFile(null)
    setModelId(null)
    setUploadStatus('uploading')
    setScaleToastDismissed(false)
    setViewMode('model')
    setPlateInfo(null)
    setPlateIndex(null)
    setObjectThumbs({})
    setObjectPickerOpen(false)
    setPlacement(null)
    setCopies(1)
    setMeshReport(null)
    return loadSampleModel(sampleId)
      .then((res) => {
        setModelId(res.model_id)
        getModelPlates(res.model_id)
          .then(applyInspection)
          .catch(() => setPlateInfo(null))
        return downloadModelFile(res.model_id)
      })
      .then((downloaded) => {
        setFile(downloaded)
        setUploadStatus('done')
      })
      .catch((err: Error) => {
        setUploadStatus('error')
        throw err
      })
  }, [applyInspection])

  // Stable reference: Viewer's effect depends on this, and an inline arrow
  // function would make it re-run (tearing down/rebuilding the three.js
  // scene) on every unrelated App re-render.
  const handleDimensions = useCallback((dims: Dimensions | null) => setDimensions(dims), [])

  const objects: ObjectInfo[] = useMemo(() => plateInfo?.objects ?? [], [plateInfo])
  const hasObjectChoice = objects.length > 1
  const isBeltPrinter = bedSize?.beltPrinterInfiniteY === true
  // On a belt printer every kept object goes in one row along the belt, so
  // which plate it came from no longer matters and the plate picker is moot.
  const beltRowActive = isBeltPrinter && ((hasObjectChoice && beltLineUp) || copies > 1)
  const keptObjects = useMemo(() => objects.filter((o) => !excludedObjects.has(o.index)), [objects, excludedObjects])
  // Position sliders: a model on a chosen printer, on a single plate, and not
  // already laid out by the belt row.
  const readyToPlace = Boolean(file && modelId && printerName && bedSize && dimensions) && !beltRowActive && copies === 1
  const multiPlate = (plateInfo?.plates.length ?? 1) > 1
  const showPositionPanel = readyToPlace && !multiPlate
  // The Rotate and move window also works on one plate of a multi-plate file (once a plate is chosen).
  const showRotateMove = readyToPlace && (!multiPlate || plateIndex !== null)
  const objectSelectionSignature = JSON.stringify({
    excluded: hasObjectChoice ? [...excludedObjects].sort((x, y) => x - y) : [],
    row: beltRowActive ? { order: beltOrder.filter((i) => !excludedObjects.has(i)), gap: beltGapMm, mode: beltRowMode } : null,
    placement: showPositionPanel ? placement : null,
    copies,
  })
  // A belt printer that lines a file's objects up: where each kept object goes (one after another, or
  // plate by plate for a multi-plate file), shown in the preview and used to size what will print.
  const rowLayout = useMemo(() => {
    if (!isBeltPrinter || !hasObjectChoice || !beltLineUp || keptObjects.length === 0) return null
    const shifts = beltRowShifts(objects, beltOrder, excludedObjects, beltGapMm, beltRowMode)
    const spans = keptObjects.map((o) => ({
      x0: o.center_x_mm - o.width_mm / 2 + shifts[o.index].dx,
      x1: o.center_x_mm + o.width_mm / 2 + shifts[o.index].dx,
      y0: o.center_y_mm - o.depth_mm / 2 + shifts[o.index].dy,
      y1: o.center_y_mm + o.depth_mm / 2 + shifts[o.index].dy,
    }))
    const extent: Dimensions = {
      x: Math.max(...spans.map((s) => s.x1)) - Math.min(...spans.map((s) => s.x0)),
      y: Math.max(...spans.map((s) => s.y1)) - Math.min(...spans.map((s) => s.y0)),
      z: Math.max(...keptObjects.map((o) => o.height_mm)),
    }
    return { shifts, extent }
  }, [isBeltPrinter, hasObjectChoice, beltLineUp, keptObjects, objects, beltOrder, excludedObjects, beltGapMm, beltRowMode])
  // What will actually print. A belt row is the lined-up layout, repeated per copy; for any other
  // multi-plate file the viewer's combined extent across plates means nothing, so no fit
  // suggestion is made at all.
  const fitDimensions: Dimensions | null =
    beltRowActive && rowLayout
      ? { x: rowLayout.extent.x, y: rowLayout.extent.y * copies + beltGapMm * (copies - 1), z: rowLayout.extent.z }
      : beltRowActive && keptObjects.length > 0
        ? {
            x: Math.max(...keptObjects.map((o) => o.width_mm)),
            y:
              keptObjects.reduce((sum, o) => sum + o.depth_mm, 0) * copies +
              beltGapMm * (keptObjects.length * copies - 1),
            z: Math.max(...keptObjects.map((o) => o.height_mm)),
          }
        : beltRowActive && dimensions
        ? { x: dimensions.x, y: dimensions.y * copies + beltGapMm * (copies - 1), z: dimensions.z }
        : dimensions
  const fitScale =
    fitDimensions && bedSize && printerName ? computeFitScale(fitDimensions, bedSize) : null
  const scalable = file ? canScaleFile(file) : true
  const showScaleToast = fitScale !== null && !scaleToastDismissed && scalable

  // Shared by the auto-fit toast (uniform factor on all three axes) and the
  // manual ScaleControls panel (which can send different factors per axis).
  const handleApplyScale = useCallback(
    (factors: Dimensions) => {
      if (!file) return
      setScaling(true)
      scaleStlFile(file, factors)
        .then((scaled) => handleFileSelected(scaled))
        .catch((err: Error) => alert(`Failed to scale model: ${err.message}`))
        .finally(() => setScaling(false))
    },
    [file, handleFileSelected],
  )

  const handleAcceptScaleToFit = useCallback(() => {
    if (fitScale === null) return
    handleApplyScale({ x: fitScale, y: fitScale, z: fitScale })
  }, [fitScale, handleApplyScale])

  // Picking a printer resets process/material to that machine's own
  // defaults (default_print_profile / default_filament_profile) --
  // matches how OrcaSlicer itself behaves when you switch printers.
  const handlePrinterChange = useCallback(
    (name: string) => {
      setPrinterName(name)
      setProcessName('')
      setFilamentSlots(buildFilamentSlots(1, ''))
      setBedSize(null)
      setNozzleDiameters([])
      setNozzleTypes([])
      setGlobalNozzleDiameter('')
      setGlobalNozzleType('undefine')
      setScaleToastDismissed(false)
      setSelectedPrinterId(null)
      setViewMode('model')
      if (!vendor || !name) return

      // Not every vendor's machine profile sets these (confirmed empirically:
      // BBL does, Afinia doesn't) -- fall back to a profile of that kind for
      // the vendor so picking a printer always leaves a slice-able selection
      // rather than silently requiring a manual pick. Prefer one actually
      // named for this printer (the "0.10mm Standard @BBL A1 0.2 nozzle"
      // convention) over just the alphabetically-first one for the vendor.
      const firstOfKind = (kind: 'process' | 'filament') => {
        const inVendor = profiles.filter((p) => p.vendor === vendor && p.kind === kind)
        const namedForPrinter = inVendor.find((p) => p.name.includes(name))
        if (namedForPrinter) return namedForPrinter.name
        if (inVendor[0]) return inVendor[0].name
        if (kind !== 'filament') return ''
        // Machine-only vendors (Voron, and 16+ others in this catalog) ship
        // no filament profiles of their own at all -- filament choice isn't
        // actually tied to printer vendor the way process profiles are, so
        // fall back to the catalog's vendor-agnostic "system" filaments
        // (OrcaSlicer's own default set) rather than leaving this empty,
        // which would otherwise permanently block both saving a printer and
        // slicing (both require a non-empty filament). Specifically prefer
        // "Generic PLA" within that set over just the first system filament
        // in whatever order the catalog happens to list them (confirmed
        // that can land on something like PA-CF -- carbon-fiber nylon
        // needing a hardened nozzle and high temps -- a bad silent default).
        const systemFilaments = profiles.filter(
          (p) => p.kind === 'filament' && p.vendor === 'OrcaFilamentLibrary',
        )
        const genericPla =
          systemFilaments.find((p) => p.name === 'Generic PLA @System') ??
          systemFilaments.find((p) => p.name.startsWith('Generic PLA'))
        if (genericPla) return genericPla.name
        if (systemFilaments[0]) return systemFilaments[0].name
        const anyFilament = profiles.find((p) => p.kind === 'filament')
        return anyFilament?.name ?? ''
      }

      getProfileDetail(vendor, 'machine', name)
        .then((detail) => {
          const defaultProcess = detail.data.default_print_profile
          const defaultFilament = detail.data.default_filament_profile
          const process =
            typeof defaultProcess === 'string'
              ? defaultProcess
              : Array.isArray(defaultProcess) && typeof defaultProcess[0] === 'string'
                ? defaultProcess[0]
                : firstOfKind('process')
          const filament =
            typeof defaultFilament === 'string'
              ? defaultFilament
              : Array.isArray(defaultFilament) && typeof defaultFilament[0] === 'string'
                ? defaultFilament[0]
                : firstOfKind('filament')
          const diameters = parsedNozzleDiameters(detail.data)
          const types = parsedNozzleTypes(detail.data)
          setProcessName(process)
          // Always exactly 1 slot on a fresh printer/vendor pick -- the user
          // adds more via the "+" control in the Material section
          // (addFilamentSlot below) rather than it being derived from
          // whatever slot count this specific catalog profile happens to
          // define.
          setFilamentSlots(buildFilamentSlots(1, filament, diameters, types))
          setBedSize(parseBedSize(detail.data))
          // A newly picked printer starts on its own default plate; the
          // material check below then moves it if the material cannot use it.
          const printerBed = typeof detail.data.default_bed_type === 'string' ? detail.data.default_bed_type : null
          setPrinterDefaultBed(printerBed)
          if (printerBed && schema.find((s) => s.key === 'curr_bed_type')?.enum_values?.includes(printerBed)) {
            setQuickSettings((prev) => ({ ...prev, curr_bed_type: printerBed }))
          }
          setNozzleDiameters(diameters)
          setNozzleTypes(types)
          setGlobalNozzleDiameter(diameters[0] != null ? String(diameters[0]) : '')
          setGlobalNozzleType(types[0] ?? 'undefine')
        })
        .catch(() => {
          setProcessName(firstOfKind('process'))
          setFilamentSlots(buildFilamentSlots(1, firstOfKind('filament')))
          setNozzleDiameters([])
          setNozzleTypes([])
        })
    },
    [vendor, profiles, schema],
  )

  // A printer was made or changed: reload the list, then select it (the list has to contain it first).
  const handlePrinterSaved = useCallback(
    (name: string) => {
      setPrinterDialog(null)
      listProfiles()
        .then((list) => {
          setProfiles(list)
          setVendor(IMPORTED_VENDOR)
          setPendingPrinter(name)
        })
        .catch(() => {
          setVendor(IMPORTED_VENDOR)
          setPendingPrinter(name)
        })
    },
    [],
  )
  useEffect(() => {
    if (pendingPrinter && vendor === IMPORTED_VENDOR && profiles.some((p) => p.kind === 'machine' && p.vendor === IMPORTED_VENDOR && p.name === pendingPrinter)) {
      handlePrinterChange(pendingPrinter)
      setPendingPrinter(null)
    }
  }, [pendingPrinter, vendor, profiles, handlePrinterChange])

  const handleVendorChange = useCallback((v: string) => {
    setVendor(v)
    setPrinterName('')
    setProcessName('')
    setFilamentSlots(buildFilamentSlots(1, ''))
    setBedSize(null)
    setNozzleDiameters([])
    setNozzleTypes([])
    setGlobalNozzleDiameter('')
    setGlobalNozzleType('undefine')
    setSelectedPrinterId(null)
    setViewMode('model')
  }, [])

  // A brim type chosen earlier (or saved in a settings profile) that does not
  // exist on a belt printer goes back to "Profile default" rather than
  // silently doing something else.
  useEffect(() => {
    if (bedSize?.beltPrinterInfiniteY && quickSettings.brim_type && !BELT_BRIM_TYPES.includes(quickSettings.brim_type)) {
      setQuickSettings((prev) => ({ ...prev, brim_type: '' }))
    }
  }, [bedSize, quickSettings.brim_type])

  // The materials in use decide which build plates make sense: read their
  // supported plates, and if the current plate is not one of them move to one
  // that is (the printer's own default when the material allows it).
  const slotProfilesKey = filamentSlots.map((s) => s.profile).filter(Boolean).join('\u0001')
  useEffect(() => {
    const names = [...new Set(slotProfilesKey ? slotProfilesKey.split('\u0001') : [])]
    if (names.length === 0) {
      setAllowedBedTypes(null)
      return
    }
    let live = true
    Promise.all(
      names.map((name) => {
        const vendorOf = profiles.find((p) => p.kind === 'filament' && p.name === name)?.vendor
        return vendorOf ? getProfileDetail(vendorOf, 'filament', name).then((d) => d.data) : Promise.resolve(null)
      }),
    )
      .then((details) => {
        if (!live) return
        const known = details.filter((d): d is Record<string, unknown> => d !== null)
        setAllowedBedTypes(known.length === names.length ? supportedBedTypes(known) : null)
      })
      .catch(() => live && setAllowedBedTypes(null))
    return () => {
      live = false
    }
  }, [slotProfilesKey, profiles])
  useEffect(() => {
    if (allowedBedTypes && allowedBedTypes.length > 0 && !allowedBedTypes.includes(quickSettings.curr_bed_type)) {
      setQuickSettings((prev) => ({ ...prev, curr_bed_type: pickBedType(allowedBedTypes, printerDefaultBed) }))
    }
  }, [allowedBedTypes, printerDefaultBed, quickSettings.curr_bed_type])

  // Reload the dropdowns after profiles were imported or deleted.
  const refreshProfiles = useCallback(() => {
    listProfiles()
      .then(setProfiles)
      .catch(() => {
        /* the existing list stays as it was */
      })
  }, [])

  // Any change to a slicing-relevant selection invalidates whatever G-code
  // preview might be showing -- it no longer reflects what a new slice
  // would produce, so drop back to the model view automatically.
  const handleProcessChange = useCallback((name: string) => {
    setProcessName(name)
    setViewMode('model')
  }, [])

  const handleFilamentSlotChange = useCallback((index: number, patch: Partial<FilamentSlot>) => {
    setFilamentSlots((prev) => prev.map((slot, i) => (i === index ? { ...slot, ...patch } : slot)))
    setViewMode('model')
  }, [])

  // A material was created or edited: reload the list first so the slot's
  // choice exists in it, then select it.
  const handleMaterialSaved = useCallback(
    (slot: number, name: string) => {
      setMaterialDialog(null)
      listProfiles()
        .then((list) => {
          setProfiles(list)
          handleFilamentSlotChange(slot, { profile: name })
        })
        .catch(() => handleFilamentSlotChange(slot, { profile: name }))
    },
    [handleFilamentSlotChange],
  )

  // Delete one of the user's own materials; the slot falls back to the
  // material it was based on, or the first one available.
  const handleDeleteCustomFilament = useCallback(
    async (slot: number, name: string) => {
      try {
        const imported = await listImportedProfiles()
        const parent = imported.find((p) => p.kind === 'filament' && p.name === name)?.inherits ?? null
        await deleteImportedProfile('filament', name)
        const list = await listProfiles()
        setProfiles(list)
        const stillThere = (n: string | null) => n !== null && list.some((p) => p.kind === 'filament' && p.name === n)
        const fallback = stillThere(parent) ? parent : list.find((p) => p.kind === 'filament')?.name ?? ''
        handleFilamentSlotChange(slot, { profile: fallback as string })
      } catch (err) {
        alert(`Failed to delete the material: ${(err as Error).message}`)
      }
    },
    [handleFilamentSlotChange],
  )

  // A fresh slot's nozzle diameter/type defaults from the last existing
  // slot (adding a physical head is usually adding one similar to what you
  // already have) -- fully editable afterward either way.
  const addFilamentSlot = useCallback(() => {
    setFilamentSlots((prev) => {
      if (prev.length >= MAX_FILAMENT_SLOTS) return prev
      const last = prev[prev.length - 1]
      return [
        ...prev,
        {
          profile: '',
          color: defaultSlotColor(prev.length),
          nozzleDiameter: last?.nozzleDiameter ?? 0.4,
          nozzleType: last?.nozzleType ?? 'undefine',
        },
      ]
    })
    setViewMode('model')
  }, [])

  const removeFilamentSlot = useCallback((index: number) => {
    setFilamentSlots((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== index) : prev))
    setViewMode('model')
  }, [])

  // Note: unlike the printer/vendor handlers, this deliberately does NOT
  // clear selectedMaterialId -- once a material profile is selected,
  // tweaking settings is "update mode" (SavedPrinters shows an "Update
  // <name>" action that overwrites it) rather than instantly disowning the
  // selection. Picking a *different* material or the blank option is what
  // changes/clears selectedMaterialId (applyMaterialProfile / handleDeselect
  // MaterialProfile, below).
  const handleQuickSettingsChange = useCallback((values: QuickSettingsValues) => {
    setQuickSettings(values)
    setViewMode('model')
  }, [])

  const handleAdvancedOverridesChange = useCallback((overrides: Record<string, string>) => {
    setAdvancedOverrides(overrides)
    setViewMode('model')
  }, [])

  // Restores a saved printer's vendor/printer/process/filament/bed-size
  // synchronously (App.tsx already has every piece of state a saved
  // printer snapshots), no network round-trip needed unlike picking a
  // printer fresh via PrinterSelect (handlePrinterChange, above).
  const applySavedPrinter = useCallback((printer: PrinterRecord) => {
    setSelectedPrinterId(printer.id)
    setVendor(printer.vendor)
    setPrinterName(printer.machine_profile)
    setProcessName(printer.process_profile)
    setFilamentSlots(
      printer.filament_profiles.length > 0
        ? printer.filament_profiles.map((profile, i) => ({
            profile,
            color: printer.filament_colors[i] ?? defaultSlotColor(i),
            nozzleDiameter: 0.4,
            nozzleType: 'undefine',
          }))
        : buildFilamentSlots(1, ''),
    )
    setBedSize(
      printer.bed_width != null && printer.bed_depth != null && printer.bed_height != null
        ? {
            width: printer.bed_width,
            depth: printer.bed_depth,
            height: printer.bed_height,
            // Also backfilled with the machine profile below.
            minX: 0,
            minY: 0,
            // Backfilled a moment later once the machine profile itself
            // loads below (a saved printer record doesn't snapshot these) --
            // false/null here just means the belt-specific placement in
            // Viewer and the GcodeViewer back-transform briefly fall back to
            // their non-belt defaults until then.
            beltPrinterInfiniteY: false,
            beltTransform: null,
          }
        : null,
    )
    setScaleToastDismissed(false)
    setViewMode('model')
    setNozzleDiameters([])
    setNozzleTypes([])
    setGlobalNozzleDiameter('')
    setGlobalNozzleType('undefine')
    // The pieces a saved printer record doesn't snapshot itself: the
    // machine profile's actual nozzle_diameter/nozzle_type values (only
    // needed at slice time) -- fetched fresh rather than blocking the
    // otherwise-synchronous restore above on it, then backfilled onto the
    // just-restored slots.
    getProfileDetail(printer.vendor, 'machine', printer.machine_profile)
      .then((detail) => {
        const diameters = parsedNozzleDiameters(detail.data)
        const types = parsedNozzleTypes(detail.data)
        setNozzleDiameters(diameters)
        setNozzleTypes(types)
        setGlobalNozzleDiameter(diameters[0] != null ? String(diameters[0]) : '')
        setGlobalNozzleType(types[0] ?? 'undefine')
        setFilamentSlots((prev) =>
          prev.map((slot, i) => ({
            ...slot,
            nozzleDiameter: diameters[i] ?? diameters[diameters.length - 1] ?? slot.nozzleDiameter,
            nozzleType: types[i] ?? types[types.length - 1] ?? slot.nozzleType,
          })),
        )
        // Re-derive from the actual profile now that it's loaded, so a
        // belt printer's beltPrinterInfiniteY flag (not part of the saved
        // printer record itself) reaches the Viewer too.
        const parsedBed = parseBedSize(detail.data)
        if (parsedBed) setBedSize(parsedBed)
      })
      .catch(() => {
        setNozzleDiameters([])
        setNozzleTypes([])
      })
  }, [])

  const handleSavePrinter = useCallback(
    (name: string, connection: PrinterConnection) => {
      return createPrinter({
        name,
        vendor,
        machine_profile: printerName,
        process_profile: processName,
        filament_profiles: filamentSlots.map((s) => s.profile),
        filament_colors: filamentSlots.map((s) => s.color),
        bed_width: bedSize?.width ?? null,
        bed_depth: bedSize?.depth ?? null,
        bed_height: bedSize?.height ?? null,
        ...connection,
      }).then((printer) => {
        setPrinters((prev) => [...prev, printer])
        setSelectedPrinterId(printer.id)
      })
    },
    [vendor, printerName, processName, filamentSlots, bedSize],
  )

  const handleUpdatePrinter = useCallback((id: string, body: PrinterUpdateRequest) => {
    return updatePrinter(id, body).then((printer) => {
      setPrinters((prev) => prev.map((p) => (p.id === id ? printer : p)))
    })
  }, [])

  const handleDeletePrinter = useCallback((id: string) => {
    deletePrinter(id)
      .then(() => {
        setPrinters((prev) => prev.filter((p) => p.id !== id))
        setSelectedPrinterId((prev) => (prev === id ? null : prev))
      })
      .catch((err: Error) => alert(`Failed to delete printer: ${err.message}`))
  }, [])

  // Restores the account's last-selected printer, exactly once, right after
  // the printers list first loads (not on every later change to it, e.g.
  // after saving a new printer -- hence keying solely off `printersLoaded`
  // flipping true rather than the `printers` array itself).
  useEffect(() => {
    if (!printersLoaded) return
    const match = authStatus.last_printer_id
      ? printers.find((p) => p.id === authStatus.last_printer_id)
      : undefined
    if (match) {
      applySavedPrinter(match)
      // Restoring a material/settings profile (if any) happens once this
      // printer's materials/settings-profiles lists load -- see the two
      // effects above, which mark restorationDone/settingsRestorationDone
      // when they settle.
    } else {
      setRestorationDone(true)
      setSettingsRestorationDone(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [printersLoaded])

  // Persists the current printer/material/settings-profile selection as the
  // account's default for next time -- but not until the initial
  // restoration (above) has fully settled on both fronts, or this would
  // race it: e.g. save (printerId, null, null) right after the printer
  // restores but before its material/settings profile does, then lose to a
  // slower-finishing restore, permanently wiping the persisted id.
  useEffect(() => {
    if (!restorationDone || !settingsRestorationDone) return
    onUpdateLastSelection(selectedPrinterId, selectedMaterialId, selectedSettingsProfileId).catch(() => {})
  }, [
    selectedPrinterId,
    selectedMaterialId,
    selectedSettingsProfileId,
    restorationDone,
    settingsRestorationDone,
    onUpdateLastSelection,
  ])

  const handleSaveMaterial = useCallback(
    (name: string) => {
      if (!selectedPrinterId) return Promise.reject(new Error('Select a saved printer first'))
      return createMaterialProfile(selectedPrinterId, {
        name,
        filament_profiles: filamentSlots.map((s) => s.profile),
        filament_colors: filamentSlots.map((s) => s.color),
      }).then((material) => {
        setMaterials((prev) => [...prev, material])
        setSelectedMaterialId(material.id)
      })
    },
    [selectedPrinterId, filamentSlots],
  )

  const handleDeleteMaterial = useCallback(
    (id: string) => {
      if (!selectedPrinterId) return
      deleteMaterialProfile(selectedPrinterId, id)
        .then(() => {
          setMaterials((prev) => prev.filter((m) => m.id !== id))
          setSelectedMaterialId((prev) => (prev === id ? null : prev))
        })
        .catch((err: Error) => alert(`Failed to delete material profile: ${err.message}`))
    },
    [selectedPrinterId],
  )

  const handleDeselectMaterial = useCallback(() => setSelectedMaterialId(null), [])

  // "Update mode": overwrites the already-selected material profile with
  // whatever's currently dialed in, instead of creating a new one.
  const handleUpdateMaterial = useCallback(() => {
    if (!selectedPrinterId || !selectedMaterialId) {
      return Promise.reject(new Error('Select a material profile first'))
    }
    return updateMaterialProfile(selectedPrinterId, selectedMaterialId, {
      filament_profiles: filamentSlots.map((s) => s.profile),
      filament_colors: filamentSlots.map((s) => s.color),
    }).then((material) => {
      setMaterials((prev) => prev.map((m) => (m.id === material.id ? material : m)))
    })
  }, [selectedPrinterId, selectedMaterialId, filamentSlots])

  const handleRenameMaterial = useCallback(
    (id: string, name: string) => {
      if (!selectedPrinterId) return Promise.reject(new Error('No printer selected'))
      return updateMaterialProfile(selectedPrinterId, id, { name }).then((material) => {
        setMaterials((prev) => prev.map((m) => (m.id === material.id ? material : m)))
      })
    },
    [selectedPrinterId],
  )

  const handleDuplicateMaterial = useCallback(
    (id: string) => {
      if (!selectedPrinterId) return
      duplicateMaterialProfile(selectedPrinterId, id)
        .then((material) => setMaterials((prev) => [...prev, material]))
        .catch((err: Error) => alert(`Failed to duplicate material profile: ${err.message}`))
    },
    [selectedPrinterId],
  )

  const handleSaveSettingsProfile = useCallback(
    (name: string) => {
      if (!selectedPrinterId) return Promise.reject(new Error('Select a saved printer first'))
      return createSettingsProfile(selectedPrinterId, {
        name,
        quick_settings: quickSettings as unknown as Record<string, string>,
        advanced_overrides: advancedOverrides,
        process_profile: processName || null,
      }).then((profile) => {
        setSettingsProfiles((prev) => [...prev, profile])
        setSelectedSettingsProfileId(profile.id)
      })
    },
    [selectedPrinterId, quickSettings, advancedOverrides, processName],
  )

  const handleDeleteSettingsProfile = useCallback(
    (id: string) => {
      if (!selectedPrinterId) return
      deleteSettingsProfile(selectedPrinterId, id)
        .then(() => {
          setSettingsProfiles((prev) => prev.filter((p) => p.id !== id))
          setSelectedSettingsProfileId((prev) => (prev === id ? null : prev))
        })
        .catch((err: Error) => alert(`Failed to delete settings profile: ${err.message}`))
    },
    [selectedPrinterId],
  )

  const handleDeselectSettingsProfile = useCallback(() => setSelectedSettingsProfileId(null), [])

  // "Update mode": overwrites the already-selected settings profile with
  // whatever's currently dialed in, instead of creating a new one.
  const handleUpdateSettingsProfile = useCallback(() => {
    if (!selectedPrinterId || !selectedSettingsProfileId) {
      return Promise.reject(new Error('Select a settings profile first'))
    }
    return updateSettingsProfile(selectedPrinterId, selectedSettingsProfileId, {
      quick_settings: quickSettings as unknown as Record<string, string>,
      advanced_overrides: advancedOverrides,
      process_profile: processName || null,
    }).then((profile) => {
      setSettingsProfiles((prev) => prev.map((p) => (p.id === profile.id ? profile : p)))
    })
  }, [selectedPrinterId, selectedSettingsProfileId, quickSettings, advancedOverrides, processName])

  const handleRenameSettingsProfile = useCallback(
    (id: string, name: string) => {
      if (!selectedPrinterId) return Promise.reject(new Error('No printer selected'))
      return updateSettingsProfile(selectedPrinterId, id, { name }).then((profile) => {
        setSettingsProfiles((prev) => prev.map((p) => (p.id === profile.id ? profile : p)))
      })
    },
    [selectedPrinterId],
  )

  const handleDuplicateSettingsProfile = useCallback(
    (id: string) => {
      if (!selectedPrinterId) return
      duplicateSettingsProfile(selectedPrinterId, id)
        .then((profile) => setSettingsProfiles((prev) => [...prev, profile]))
        .catch((err: Error) => alert(`Failed to duplicate settings profile: ${err.message}`))
    },
    [selectedPrinterId],
  )

  // Poll the active job until it leaves queued/running.
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  useEffect(() => {
    if (!currentJob || !ACTIVE_STATUSES.includes(currentJob.status)) {
      if (pollRef.current) clearInterval(pollRef.current)
      return
    }
    pollRef.current = setInterval(() => {
      getJob(currentJob.id)
        .then((job) => {
          setCurrentJob(job)
          if (!ACTIVE_STATUSES.includes(job.status)) {
            setSlicing(false)
            listJobs().then(setHistory).catch(() => {})
            if (job.status === 'succeeded') viewJobGcode(job.id)
          }
        })
        .catch(() => {
          if (pollRef.current) clearInterval(pollRef.current)
        })
    }, POLL_INTERVAL_MS)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentJob?.id, currentJob?.status])

  const fileRoles = useMemo(() => fileRolesFromInspection(plateInfo), [plateInfo])

  // Resets whenever a new file's roles are known -- a single-role file
  // (the common case: a plain STL, or a .3mf with no detected
  // multi-material info) defaults to the printer's first configured slot
  // so a plain single-color print needs no extra step, same as before
  // this feature existed; overridable via the nozzle-assignment UI below.
  // A genuinely multi-role file starts fully unassigned instead -- there's
  // no safe default mapping to guess (guessing wrong here is exactly what
  // crashed the CLI once already), so slicing stays blocked until every
  // role has an explicit, deliberate choice.
  useEffect(() => {
    setRoleNozzleAssignments(fileRoles.length === 1 ? [0] : fileRoles.map(() => null))
  }, [fileRoles])

  const allRolesAssigned = roleNozzleAssignments.every(
    (slotIdx) => slotIdx !== null && filamentSlots[slotIdx]?.profile,
  )
  // Exactly one filament per file role, chosen from the printer's real,
  // catalog-backed configured slots -- never more or fewer than the file
  // actually needs (confirmed via direct testing against a real downloaded
  // multi-color model: sending a mismatched count, e.g. all 4 configured
  // slots for a file that only needs 2, crashes the OrcaSlicer CLI outright
  // rather than failing gracefully).
  const effectiveFilamentProfiles = useMemo(
    () => roleNozzleAssignments.map((slotIdx) => (slotIdx !== null ? (filamentSlots[slotIdx]?.profile ?? '') : '')),
    [roleNozzleAssignments, filamentSlots],
  )

  // Only worth showing when there's an actual choice to make: either the
  // printer has more than one nozzle to pick from, or the file itself
  // needs more than one color (in which case a per-role mapping is
  // mandatory even on a printer with just one configured slot repeated).
  const showNozzleAssignment = filamentSlots.length > 1 || fileRoles.length > 1

  // The 3D preview should show what will actually print -- once a role has
  // a nozzle assigned, substitute that slot's own color for the file's
  // original one; a role with no assignment yet keeps showing the file's
  // color as a placeholder. Recomputed on every assignment change, which
  // is what makes the preview update live as roles are picked.
  const renderColorTree = useMemo(() => {
    const assignedColorFor = (extruder: number | null): string | undefined => {
      if (extruder === null) return undefined
      const slotIdx = roleNozzleAssignments[extruder - 1]
      return slotIdx !== null ? filamentSlots[slotIdx]?.color : undefined
    }
    const substitute = (nodes: ColorNode[]): ColorNode[] =>
      nodes.map((node) => {
        if (node.children.length > 0) return { ...node, children: substitute(node.children) }
        const assignedColor = assignedColorFor(node.extruder)
        const triangleColors = node.triangle_extruders
          ? node.triangle_extruders.map((extruder, i) => assignedColorFor(extruder) ?? node.triangle_colors?.[i] ?? null)
          : node.triangle_colors
        if (!assignedColor && triangleColors === node.triangle_colors) return node
        return { ...node, color: assignedColor ?? node.color, triangle_colors: triangleColors ?? null }
      })
    return substitute(plateInfo?.color_tree ?? [])
  }, [plateInfo, roleNozzleAssignments, filamentSlots])
  const showPlatePicker = (plateInfo?.plates.length ?? 0) > 1 && !beltRowActive
  // One plate of a multi-plate file at a time in the preview (not when a belt
  // row lays everything out end to end).
  const shownObjects = useMemo(
    () => (showPlatePicker && plateIndex !== null ? objects.filter((o) => o.plate === plateIndex).map((o) => o.index) : undefined),
    [showPlatePicker, plateIndex, objects],
  )

  // Part of the slice signature (below) so a nozzle diameter/type edit
  // counts as "you changed something" the same way any other slice-
  // affecting setting does.
  const nozzleSettingsSignature = isMultiHeadPrinter
    ? JSON.stringify(filamentSlots.map((s) => [s.nozzleDiameter, s.nozzleType]))
    : JSON.stringify({ globalNozzleDiameter, globalNozzleType })

  const currentSignature = useMemo(
    () =>
      computeSliceSignature(
        modelId,
        printerName,
        processName,
        effectiveFilamentProfiles,
        plateIndex,
        quickSettings,
        advancedOverrides,
        nozzleSettingsSignature,
        objectSelectionSignature,
        roleNozzleAssignments,
      ),
    [
      modelId,
      printerName,
      processName,
      effectiveFilamentProfiles,
      plateIndex,
      quickSettings,
      advancedOverrides,
      nozzleSettingsSignature,
      objectSelectionSignature,
      roleNozzleAssignments,
    ],
  )
  // Only a *successful* prior slice blocks re-slicing -- a failed job with
  // unchanged settings should still be retryable (e.g. a transient error).
  const alreadySliced = currentJob?.status === 'succeeded' && lastSlicedSignature === currentSignature
  const filamentSlotsFilled = filamentSlots.every((s) => s.profile)
  // A multi-plate file requires an explicit pick before slicing is enabled
  // -- there's no good "slice all of them" default once a specific plate
  // picker exists (see plan: pre-slice picker, not slice-everything).
  const plateChosenIfNeeded = !showPlatePicker || plateIndex !== null
  // Something must be left to print -- and, when one plate is picked, on that plate.
  const objectSelectionOk =
    !hasObjectChoice ||
    (keptObjects.length > 0 && (showPlatePicker && plateIndex !== null ? keptObjects.some((o) => o.plate === plateIndex) : true))
  const canSlice =
    Boolean(modelId && printerName && processName && allRolesAssigned) &&
    plateChosenIfNeeded &&
    objectSelectionOk &&
    !alreadySliced

  const handleSlice = useCallback(() => {
    if (!modelId || !printerName || !processName || !allRolesAssigned || !plateChosenIfNeeded || !objectSelectionOk) return
    setSlicing(true)
    setViewMode('model')
    setLastSlicedSignature(currentSignature)
    const overrides: Record<string, string> = {
      ...advancedOverrides,
      layer_height: quickSettings.layer_height,
      sparse_infill_density: `${quickSettings.sparse_infill_density}%`,
      wall_loops: quickSettings.wall_loops,
      sparse_infill_pattern: quickSettings.sparse_infill_pattern,
      curr_bed_type: quickSettings.curr_bed_type,
      enable_support: quickSettings.enable_support,
      enable_prime_tower: quickSettings.enable_prime_tower,
    }
    // Empty means "use the process profile's own value" -- see QuickSettings.
    if (quickSettings.seam_position) overrides.seam_position = quickSettings.seam_position
    if (quickSettings.brim_type) overrides.brim_type = quickSettings.brim_type
    // Only meaningful (and only worth sending) when support is actually on.
    if (quickSettings.enable_support === '1') {
      overrides.support_type = quickSettings.support_type
      // NOTE: the real FDM option is "support_on_build_plate_only" --
      // "support_buildplate_only" is a same-named-looking but unrelated SLA
      // option (SLAPrintObjectConfig, PrintConfig.cpp) that silently no-ops
      // for every FDM print. Confirmed via direct API test: overriding the
      // wrong key left filament_used_g unchanged, while the correct key
      // changed it (19.52g -> 17.24g on a support-enabled Benchy).
      overrides.support_on_build_plate_only = quickSettings.support_buildplate_only
    }
    // Nozzle diameter & type: a genuine multi-head printer (isMultiHeadPrinter)
    // can have a different nozzle installed per head, so each slot carries
    // its own; a single-nozzle printer shares one physical hotend across
    // every material slot, so one global value applies to all of them (see
    // the Material section below).
    // nozzle_diameter (coFloats) and nozzle_type (coEnums) both deserialize
    // as COMMA-separated on this CLI -- confirmed directly against
    // libslic3r/Config.hpp's ConfigOptionFloatsTempl/ConfigOptionEnumsGenericTempl
    // ::deserialize, which both split on ',' (only a plain coStrings field,
    // e.g. filament_type, is genuinely semicolon-separated). A semicolon-
    // joined value doesn't error for nozzle_diameter -- istream's `>>` for a
    // double just silently stops at the first ';' -- so this previously
    // went undetected: sending "0.4;0.4;0.6;0.6" silently collapsed to a
    // single-element nozzle_diameter of just 0.4, discarding every value
    // after the first semicolon. Confirmed via direct CLI testing that a
    // comma-joined value round-trips correctly as the full array.
    if (isMultiHeadPrinter) {
      const diameters = filamentSlots.map((s) => s.nozzleDiameter)
      if (diameters.every((d) => Number.isFinite(d) && d > 0)) {
        overrides.nozzle_diameter = diameters.join(',')
        // Confirmed via direct CLI testing: a mixed-diameter toolchanger's
        // own bundled process profile can fail slicing outright ("Bridge
        // line width must not exceed nozzle diameter") because its default
        // bridge_line_width was sized for its smaller nozzle but validated
        // against its largest -- clamp to the smallest configured nozzle
        // whenever there's genuine diameter variation, unless the user has
        // already set this explicitly via Advanced settings.
        if (new Set(diameters).size > 1 && !('bridge_line_width' in advancedOverrides)) {
          overrides.bridge_line_width = String(Math.min(...diameters))
        }
      }
      if (filamentSlots.some((s) => s.nozzleType && s.nozzleType !== 'undefine')) {
        overrides.nozzle_type = filamentSlots.map((s) => s.nozzleType || 'undefine').join(',')
      }
    } else {
      const dia = Number(globalNozzleDiameter)
      if (globalNozzleDiameter.trim() !== '' && Number.isFinite(dia) && dia > 0) {
        overrides.nozzle_diameter = Array(filamentSlots.length || 1).fill(dia).join(',')
      }
      if (globalNozzleType && globalNozzleType !== 'undefine') {
        overrides.nozzle_type = Array(filamentSlots.length || 1).fill(globalNozzleType).join(',')
      }
    }
    // A file's role N (0-based roleIdx) is always embedded as extruder
    // (roleIdx + 1) -- confirmed the same 1-based numbering is used for
    // both plain per-object extruder tags and per-triangle painted
    // assignments (both ultimately resolve via filament_colors[extruder -
    // 1], see api/app/threemf.py's _build_color_node). The user assigning
    // that role to filamentSlots[slotIdx] means "physically print this
    // with extruder slotIdx + 1" -- only emit a pair when that actually
    // differs from the file's own default (identity), so the common case
    // (single material, or roles already left in their original order)
    // sends nothing and behaves exactly as before. Requires the vendored
    // OrcaSlicer fork's --remap-filament-extruder CLI patch, which remaps
    // both the plain per-object extruder config and any per-triangle
    // MMU-painted color assignment via libslic3r's own
    // remap_model_filament_slots -- confirmed via direct CLI testing.
    const remapPairs: string[] = []
    roleNozzleAssignments.forEach((slotIdx, roleIdx) => {
      if (slotIdx === null) return
      const oldExtruder = roleIdx + 1
      const newExtruder = slotIdx + 1
      if (oldExtruder !== newExtruder) remapPairs.push(`${oldExtruder}:${newExtruder}`)
    })
    const needsRemap = remapPairs.length > 0
    if (needsRemap) {
      overrides.remap_filament_extruder = remapPairs.join(',')
    }
    // Best-effort: a snapshot of exactly what's on screen right now (the
    // file's own colors, or the user's chosen nozzle-to-slot substitution)
    // gets embedded into the gcode as its preview thumbnail server-side --
    // see api/app/gcode_thumbnail.py for why this happens client-side
    // instead of in the slicer engine. Strips the "data:image/png;base64,"
    // prefix; a capture failure (nothing loaded yet, tainted canvas) just
    // means no preview, not a blocked slice.
    const previewDataUrl = viewerRef.current?.capturePreview()
    const previewImageBase64 = previewDataUrl?.split(',')[1]
    createJob({
      model_id: modelId,
      printer_profile: printerName,
      process_profile: processName,
      preview_image_base64: previewImageBase64,
      // Confirmed via direct CLI testing: --load-filaments position N
      // always means physical extruder N (1-based) -- once a remap is in
      // play, the file can end up using non-sequential/sparse extruder
      // numbers (e.g. 2 and 4), and the array must be DENSE, sized to
      // cover every configured physical slot, not just "as many as the
      // file's own role count" (that narrower rule is what the no-remap
      // path below still uses, and remains correct for it: today's files
      // always use sequential extruders from 1).
      filament_profiles: needsRemap ? filamentSlots.map((s) => s.profile) : effectiveFilamentProfiles,
      setting_overrides: overrides,
      plate_index: plateIndex ?? undefined,
      placement: showPositionPanel && placement ? placement : undefined,
      copies: copies > 1 ? copies : undefined,
      excluded_objects: hasObjectChoice ? [...excludedObjects].sort((x, y) => x - y) : undefined,
      belt_layout: beltRowActive
        ? { order: beltOrder.filter((i) => !excludedObjects.has(i)), gap_mm: beltGapMm, mode: beltRowMode }
        : undefined,
    })
      .then(setCurrentJob)
      .catch((err: Error) => {
        setSlicing(false)
        alert(`Failed to start slicing job: ${err.message}`)
      })
  }, [
    modelId,
    printerName,
    processName,
    allRolesAssigned,
    plateChosenIfNeeded,
    objectSelectionOk,
    hasObjectChoice,
    showPositionPanel,
    placement,
    copies,
    excludedObjects,
    beltRowActive,
    beltOrder,
    beltGapMm,
    beltRowMode,
    effectiveFilamentProfiles,
    plateIndex,
    quickSettings,
    advancedOverrides,
    filamentSlots,
    roleNozzleAssignments,
    isMultiHeadPrinter,
    globalNozzleDiameter,
    globalNozzleType,
    currentSignature,
  ])

  // On a belt printer a multi-object file with "line up" off goes through the
  // slicer's own arrange, which can fail to fit the objects on the bed. Offer
  // the row layout instead, and slice again if the user agrees.
  const needsLineUpQuestion =
    currentJob?.status === 'failed' &&
    Boolean(currentJob.error?.includes('over the boundary of the heated bed')) &&
    isBeltPrinter &&
    hasObjectChoice &&
    !beltRowActive &&
    lineUpAnsweredFor !== currentJob.id
  useEffect(() => {
    if (retryAfterLineUp && beltRowActive) {
      setRetryAfterLineUp(false)
      handleSlice()
    }
  }, [retryAfterLineUp, beltRowActive, handleSlice])

  return (
    <div className="app">
      <header className="app-header">
        <h1>
          <img src="/icon-192.png" alt="" width={46} height={46} />
          TridentSlicer
        </h1>
        <SettingsMenu
          status={authStatus}
          onSwitchToMulti={onSwitchToMulti}
          onSwitchToSingle={onSwitchToSingle}
          onCreateUser={onCreateUser}
          onLogout={onLogout}
          sampleModels={sampleModels}
          onLoadSample={handleLoadSample}
        />
      </header>

      {catalogError && (
        <div className="banner-error">Failed to load printer/settings catalog: {catalogError}</div>
      )}

      <main className="app-main">
        <section className="panel panel-viewer">
          {showGcode && viewedJobId ? (
            <>
              <GcodeViewer
                jobId={viewedJobId}
                filamentUsedGrams={filamentGramsOf(
                  [currentJob, ...history].find((j) => j?.id === viewedJobId) ?? null,
                )}
                beltTransform={viewedJobBeltTransform}
                onBackToModel={backToModelView}
              />
              {selectedPrinter?.print_host && (
                <SendToPrinterControl
                  key={viewedJobId}
                  printer={selectedPrinter}
                  jobId={viewedJobId}
                  onSend={handleSendToPrinter}
                />
              )}
            </>
          ) : (
            <>
              <Uploader
                onFileSelected={handleFileSelected}
                fileName={file?.name ?? null}
                uploadStatus={uploadStatus}
                meshNote={meshReport?.fixed.length ? 'auto-fixed' : meshReport?.warnings.length ? 'mesh not watertight' : null}
              />
              <Viewer
                ref={viewerRef}
                file={file}
                onDimensions={handleDimensions}
                bedSize={bedSize}
                colorTree={renderColorTree}
                filamentUsedGrams={filamentGramsOf(currentJob)}
                supportEnabled={quickSettings.enable_support === '1'}
                excludedObjects={hasObjectChoice ? [...excludedObjects] : undefined}
                placement={showPositionPanel ? placement : null}
                shownObjects={shownObjects}
                rowShifts={copies === 1 ? (rowLayout?.shifts ?? null) : null}
                onObjectThumbnails={setObjectThumbs}
              />
              {dimensions && (
                <>
                  <div className="dimensions-readout">
                    {dimensions.x.toFixed(1)} × {dimensions.y.toFixed(1)} × {dimensions.z.toFixed(1)} mm
                  </div>
                  <ScaleControls
                    dimensions={dimensions}
                    onApply={handleApplyScale}
                    applying={scaling}
                    unsupportedReason={scalable ? undefined : SCALE_UNSUPPORTED_MESSAGE}
                  />
                </>
              )}
              {showRotateMove && bedSize && dimensions && (
                <PositionPanel
                  bedSize={bedSize}
                  plateSummary={
                    multiPlate
                      ? `Plate ${plateIndex}: ${objects.filter((o) => o.plate === plateIndex).length} object${objects.filter((o) => o.plate === plateIndex).length === 1 ? '' : 's'}`
                      : undefined
                  }
                  supportEnabled={quickSettings.enable_support === '1'}
                  placement={placement}
                  onPlacementChange={(p) => {
                    setPlacement(p)
                    setViewMode('model')
                  }}
                  onOpen={() => setRotateMoveOpen(true)}
                />
              )}
              {hasObjectChoice && (
                <div className="field-group objects-button-row">
                  <button type="button" className="link-button" onClick={() => setObjectPickerOpen(true)}>
                    Objects ({keptObjects.length} of {objects.length} selected)
                  </button>
                  {keptObjects.length === 0 && <span className="field-error">Nothing selected to print</span>}
                  {keptObjects.length > 0 && !objectSelectionOk && (
                    <span className="field-error">Every object on the chosen plate is left out</span>
                  )}
                </div>
              )}
              {objectPickerOpen && hasObjectChoice && (
                <ObjectPicker
                  objects={objects}
                  thumbnails={objectThumbs}
                  excluded={excludedObjects}
                  onExcludedChange={setExcludedObjects}
                  isBelt={isBeltPrinter}
                  lineUp={beltLineUp}
                  onLineUpChange={setBeltLineUp}
                  order={beltOrder}
                  onOrderChange={setBeltOrder}
                  rowMode={beltRowMode}
                  onRowModeChange={setBeltRowMode}
                  plateNames={Object.fromEntries((plateInfo?.plates ?? []).map((p) => [p.index, p.name ?? `Plate ${p.index}`]))}
                  gapMm={beltGapMm}
                  onGapChange={setBeltGapMm}
                  onClose={() => setObjectPickerOpen(false)}
                />
              )}
              {showPlatePicker && plateInfo && (
                <PlatePicker plates={plateInfo.plates} plateIndex={plateIndex} onChange={setPlateIndex} />
              )}
              {modelId && showNozzleAssignment && (
                <div className="field-group nozzle-assignment">
                  <span>
                    {fileRoles.length > 1
                      ? 'This file uses multiple colors -- assign each to a nozzle'
                      : 'Which nozzle should print this?'}
                  </span>
                  {fileRoles.map((role, roleIdx) => (
                    <div className="nozzle-assignment-row" key={roleIdx}>
                      {fileRoles.length > 1 && (
                        <>
                          <span
                            className="nozzle-assignment-role-swatch"
                            style={role.color ? { background: role.color } : undefined}
                            title={role.color ?? 'Unknown color'}
                          />
                          <span className="nozzle-assignment-role-label">
                            Color {roleIdx + 1}
                            {role.name ? ` — ${role.name}` : ''}
                          </span>
                        </>
                      )}
                      <select
                        value={roleNozzleAssignments[roleIdx] ?? ''}
                        onChange={(e) => {
                          const value = e.target.value === '' ? null : Number(e.target.value)
                          setRoleNozzleAssignments((prev) => prev.map((v, i) => (i === roleIdx ? value : v)))
                        }}
                      >
                        <option value="" disabled>
                          Choose a nozzle…
                        </option>
                        {filamentSlots.map((slot, slotIdx) => (
                          <option key={slotIdx} value={slotIdx}>
                            {`Slot ${slotIdx + 1} (${colorLabel(slot.color)})${slot.profile ? ` — ${slot.profile}` : ''}`}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </section>

        <section className="panel panel-settings">
          <h2>Printer, material &amp; settings</h2>
          <SavedPrinters
            printers={printers}
            selectedPrinterId={selectedPrinterId}
            onSelectPrinter={applySavedPrinter}
            canSaveCurrent={Boolean(vendor && printerName && processName && filamentSlotsFilled)}
            onSavePrinter={handleSavePrinter}
            onUpdatePrinter={handleUpdatePrinter}
            onDeletePrinter={handleDeletePrinter}
          />
          <details
            className="settings-collapsible"
            open={printerSettingsOpen}
            onToggle={(e) => setPrinterSettingsOpen(e.currentTarget.open)}
          >
            <summary>Printer settings{selectedPrinter ? ` (${selectedPrinter.name})` : ''}</summary>
            <PrinterSelect
              profiles={profiles}
              vendor={vendor}
              printerName={printerName}
              processName={processName}
              onVendorChange={handleVendorChange}
              onPrinterChange={handlePrinterChange}
              onProcessChange={handleProcessChange}
              onImportClick={() => setImportOpen(true)}
              onExportClick={() => setExportOpen(true)}
              onNewPrinter={() => setPrinterDialog({ mode: 'create' })}
              onEditPrinter={() => setPrinterDialog({ mode: 'edit' })}
              onDeleteImportedPrinter={() => {
                if (!printerName) return
                deleteImportedProfile('machine', printerName)
                  .then(() => {
                    handleVendorChange(vendor)
                    refreshProfiles()
                  })
                  .catch((err: Error) => alert(`Failed to delete the imported printer: ${err.message}`))
              }}
            />
          </details>

          <details
            className="settings-collapsible"
            open={materialSectionOpen}
            onToggle={(e) => setMaterialSectionOpen(e.currentTarget.open)}
          >
            <summary>Material{selectedMaterial ? ` (${selectedMaterial.name})` : ''}</summary>
            {!isMultiHeadPrinter && (
              <div className="field-group nozzle-diameter-global">
                <label>
                  Nozzle diameter (mm)
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    placeholder="e.g. 0.4"
                    value={globalNozzleDiameter}
                    onChange={(e) => setGlobalNozzleDiameter(e.target.value)}
                  />
                </label>
                <label>
                  Nozzle type
                  <select value={globalNozzleType} onChange={(e) => setGlobalNozzleType(e.target.value)}>
                    {(schema.find((s) => s.key === 'nozzle_type')?.enum_values ?? FALLBACK_NOZZLE_TYPES).map(
                      (t) => (
                        <option key={t} value={t}>
                          {nozzleTypeLabel(t)}
                        </option>
                      ),
                    )}
                  </select>
                </label>
              </div>
            )}
            {filamentSlots.map((slot, i) => (
              <div className="filament-slot-row" key={i}>
                <FilamentSelect
                  profiles={profiles}
                  vendor={vendor}
                  printerName={printerName}
                  filamentName={slot.profile}
                  onFilamentChange={(name) => handleFilamentSlotChange(i, { profile: name })}
                  onNewMaterial={(base) => setMaterialDialog({ mode: 'create', slot: i, base: { vendor: base.vendor, name: base.name } })}
                  onEditMaterial={(m) => setMaterialDialog({ mode: 'edit', slot: i, base: { vendor: m.vendor, name: m.name } })}
                  onDeleteMaterial={(m) => void handleDeleteCustomFilament(i, m.name)}
                  label={filamentSlots.length > 1 ? `Slot ${i + 1} material` : 'Material'}
                  accessory={
                    <input
                      type="color"
                      className="filament-slot-color-input"
                      value={slot.color}
                      onChange={(e) => handleFilamentSlotChange(i, { color: e.target.value })}
                      aria-label={`Slot ${i + 1} color`}
                    />
                  }
                  belowLabel={
                    <div className="color-preset-row">
                      {COLOR_PRESETS.map(({ hex, name }) => (
                        <button
                          key={hex}
                          type="button"
                          className={`color-preset-swatch${slot.color === hex ? ' selected' : ''}`}
                          style={{ background: hex }}
                          aria-label={name}
                          title={name}
                          onClick={() => handleFilamentSlotChange(i, { color: hex })}
                        />
                      ))}
                    </div>
                  }
                />
                {isMultiHeadPrinter && (
                  <div className="field-group nozzle-diameter-per-slot">
                    <label>
                      {`Slot ${i + 1} nozzle diameter (mm)`}
                      <input
                        type="number"
                        step="0.1"
                        min="0"
                        value={slot.nozzleDiameter}
                        onChange={(e) =>
                          handleFilamentSlotChange(i, { nozzleDiameter: Number(e.target.value) })
                        }
                      />
                    </label>
                    <label>
                      {`Slot ${i + 1} nozzle type`}
                      <select
                        value={slot.nozzleType}
                        onChange={(e) => handleFilamentSlotChange(i, { nozzleType: e.target.value })}
                      >
                        {(schema.find((s) => s.key === 'nozzle_type')?.enum_values ?? FALLBACK_NOZZLE_TYPES).map(
                          (t) => (
                            <option key={t} value={t}>
                              {nozzleTypeLabel(t)}
                            </option>
                          ),
                        )}
                      </select>
                    </label>
                  </div>
                )}
                {filamentSlots.length > 1 && (
                  <button
                    type="button"
                    className="link-button danger-text filament-slot-remove"
                    onClick={() => removeFilamentSlot(i)}
                    aria-label={`Remove slot ${i + 1}`}
                  >
                    ✕ Remove slot
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              className="link-button filament-slot-add"
              onClick={addFilamentSlot}
              disabled={filamentSlots.length >= MAX_FILAMENT_SLOTS}
            >
              + Add material slot
            </button>
            {selectedPrinterId && (
              <SavedProfilePicker
                label="material profile"
                profiles={materials}
                selectedId={selectedMaterialId}
                onSelect={applyMaterialProfile}
                onDeselect={handleDeselectMaterial}
                onSave={handleSaveMaterial}
                onUpdate={handleUpdateMaterial}
                onRename={handleRenameMaterial}
                onDuplicate={handleDuplicateMaterial}
                onDelete={handleDeleteMaterial}
              />
            )}
          </details>

          <details
            className="settings-collapsible"
            open={settingsSectionOpen}
            onToggle={(e) => setSettingsSectionOpen(e.currentTarget.open)}
          >
            <summary>Settings{selectedSettingsProfile ? ` (${selectedSettingsProfile.name})` : ''}</summary>
            <QuickSettings
              schema={schema}
              values={quickSettings}
              onChange={handleQuickSettingsChange}
              isBelt={bedSize?.beltPrinterInfiniteY === true}
              allowedBedTypes={allowedBedTypes}
            />
            {selectedPrinterId && (
              <SavedProfilePicker
                label="settings profile"
                profiles={settingsProfiles}
                selectedId={selectedSettingsProfileId}
                onSelect={applySettingsProfile}
                onDeselect={handleDeselectSettingsProfile}
                onSave={handleSaveSettingsProfile}
                onUpdate={handleUpdateSettingsProfile}
                onRename={handleRenameSettingsProfile}
                onDuplicate={handleDuplicateSettingsProfile}
                onDelete={handleDeleteSettingsProfile}
              />
            )}
          </details>

          <AdvancedSettings
            schema={schema}
            overrides={advancedOverrides}
            onChange={handleAdvancedOverridesChange}
            excludeKeys={QUICK_SETTING_KEYS}
          />

          {modelId && printerName && (
            <CopiesControl
              copies={copies}
              onCopiesChange={(n) => {
                setCopies(n)
                setViewMode('model')
              }}
              isBelt={isBeltPrinter}
              gapMm={beltGapMm}
              onGapChange={setBeltGapMm}
              copyLengthMm={
                keptObjects.length > 0
                  ? keptObjects.reduce((sum, o) => sum + o.depth_mm, 0) + beltGapMm * (keptObjects.length - 1)
                  : (dimensions?.y ?? 0)
              }
            />
          )}

          <JobPanel
            canSlice={canSlice}
            alreadySliced={alreadySliced}
            onSlice={handleSlice}
            slicing={slicing}
            currentJob={currentJob}
            history={history}
            onPreview={viewJobGcode}
            onDelete={handleDeleteJob}
          />
        </section>
      </main>

      {needsLineUpQuestion && currentJob && (
        <div className="confirm-backdrop" role="alertdialog" aria-modal="true" aria-label="Line the objects up along the belt?">
          <div className="confirm-dialog">
            <p>
              These objects don&rsquo;t fit side by side when the slicer arranges them on the belt bed. Slice them lined up along the belt
              instead?
            </p>
            <div className="confirm-actions">
              <button type="button" className="toast-dismiss" onClick={() => setLineUpAnsweredFor(currentJob.id)}>
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  setLineUpAnsweredFor(currentJob.id)
                  setBeltLineUp(true)
                  setRetryAfterLineUp(true)
                }}
              >
                Line them up and slice
              </button>
            </div>
          </div>
        </div>
      )}
      {importOpen && <ProfileImportDialog onClose={() => setImportOpen(false)} onChanged={refreshProfiles} />}
      {exportOpen && <ExportDialog onClose={() => setExportOpen(false)} />}
      {printerDialog && (
        <PrinterDialog
          mode={printerDialog.mode}
          current={
            printerDialog.mode === 'edit' || printerName
              ? { vendor: printerDialog.mode === 'edit' ? IMPORTED_VENDOR : vendor, name: printerName }
              : null
          }
          profiles={profiles}
          schema={schema}
          onClose={() => setPrinterDialog(null)}
          onSaved={handlePrinterSaved}
        />
      )}
      {rotateMoveOpen && file && bedSize && showRotateMove && (
        <RotateMoveDialog
          file={file}
          bedSize={bedSize}
          supportEnabled={quickSettings.enable_support === '1'}
          placement={multiPlate ? null : placement}
          objectNames={objects.map((o) => o.name)}
          thumbnails={objectThumbs}
          plateObjects={multiPlate ? objects.filter((o) => o.plate === plateIndex).map((o) => o.index) : undefined}
          busyOp={positionBusy}
          onClose={() => setRotateMoveOpen(false)}
          onPlace={(p) => {
            setPlacement(p)
            setViewMode('model')
          }}
          onTransform={handleTransformModel}
          onTransformObjects={handleTransformObjects}
          onAutoOrient={() => runModelOp('orient')}
          onAutoArrange={() => runModelOp('arrange')}
        />
      )}
      {materialDialog && (
        <MaterialDialog
          mode={materialDialog.mode}
          base={materialDialog.base}
          printerName={printerName}
          onClose={() => setMaterialDialog(null)}
          onSaved={(name) => handleMaterialSaved(materialDialog.slot, name)}
        />
      )}
      {meshReport && !meshToastDismissed && (
        <div className="toast toast-top" role="status">
          <div className="toast-message">
            {meshReport.fixed.length > 0 && (
              <p>
                <strong>Auto-fixed a non-manifold file.</strong> {meshReport.fixed.join('; ')}.
              </p>
            )}
            {meshReport.warnings.map((w) => (
              <p key={w}>{w}</p>
            ))}
          </div>
          <div className="toast-actions">
            <button type="button" className="toast-dismiss" onClick={() => setMeshToastDismissed(true)}>
              Dismiss
            </button>
          </div>
        </div>
      )}
      {showScaleToast && fitDimensions && bedSize && fitScale !== null && (
        <div className="toast">
          <div className="toast-message">
            This model ({fitDimensions.x.toFixed(0)} × {fitDimensions.y.toFixed(0)} ×{' '}
            {fitDimensions.z.toFixed(0)} mm) is larger than {printerName}&rsquo;s build volume (
            {bedSize.width.toFixed(0)} × {bedSize.depth.toFixed(0)} × {bedSize.height.toFixed(0)}{' '}
            mm). Scale it down to {Math.round(fitScale * 100)}% to fit?
          </div>
          <div className="toast-actions">
            <button type="button" onClick={handleAcceptScaleToFit} disabled={scaling}>
              {scaling ? 'Scaling…' : 'Scale to fit'}
            </button>
            <button
              type="button"
              className="toast-dismiss"
              onClick={() => setScaleToastDismissed(true)}
              disabled={scaling}
            >
              Dismiss
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
