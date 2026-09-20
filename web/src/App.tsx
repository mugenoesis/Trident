import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import {
  createJob,
  createMaterialProfile,
  createPrinter,
  deleteJob,
  deleteMaterialProfile,
  deletePrinter,
  downloadModelFile,
  duplicateMaterialProfile,
  getJob,
  getModelPlates,
  getProfileDetail,
  getSettingsSchema,
  listJobs,
  listMaterialProfiles,
  listPrinters,
  listProfiles,
  listSampleModels,
  loadSampleModel,
  sendToPrinter,
  updateMaterialProfile,
  updatePrinter,
  uploadModel,
} from './api'
import {
  type BedSize,
  type Dimensions,
  computeFitScale,
  parseBedSize,
  scaleStlFile,
} from './dimensions'
import AdvancedSettings from './components/AdvancedSettings'
import FilamentSelect from './components/FilamentSelect'
import GcodeViewer from './components/GcodeViewer'
import JobPanel from './components/JobPanel'
import LoginGate from './components/LoginGate'
import PlatePicker from './components/PlatePicker'
import PrinterSelect from './components/PrinterSelect'
import QuickSettings, {
  QUICK_SETTING_KEYS,
  defaultQuickSettings,
  type QuickSettingsValues,
} from './components/QuickSettings'
import SavedPrinters from './components/SavedPrinters'
import ScaleControls from './components/ScaleControls'
import SendToPrinterControl from './components/SendToPrinterControl'
import SettingsMenu from './components/SettingsMenu'
import SetupGate from './components/SetupGate'
import Uploader from './components/Uploader'
import Viewer from './components/Viewer'
import type {
  JobRecord,
  MaterialProfileRecord,
  PrinterConnection,
  PrinterRecord,
  PrinterUpdateRequest,
  ProfileSummary,
  SampleModelSummary,
  SettingDef,
  ThreeMfInspection,
} from './types'
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

function computeSliceSignature(
  modelId: string | null,
  printerName: string,
  processName: string,
  effectiveFilamentProfiles: string[],
  plateIndex: number | null,
  quickSettings: QuickSettingsValues,
  advancedOverrides: Record<string, string>,
): string {
  return JSON.stringify({
    modelId,
    printerName,
    processName,
    effectiveFilamentProfiles,
    plateIndex,
    quickSettings: sortedEntries(quickSettings as unknown as Record<string, unknown>),
    advancedOverrides: sortedEntries(advancedOverrides),
  })
}

interface FilamentSlot {
  profile: string
  color: string
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

// One slot per physical extruder/AMS slot -- length driven by the selected
// machine profile's nozzle_diameter array (see handlePrinterChange below).
// All fresh slots default to the same profile; the user can then pick
// something different per slot.
function buildFilamentSlots(count: number, defaultProfile: string): FilamentSlot[] {
  return Array.from({ length: Math.max(1, count) }, (_, i) => ({
    profile: defaultProfile,
    color: defaultSlotColor(i),
  }))
}

// nozzle_diameter's array length is the reliable signal for physical
// extruder/AMS-slot count (confirmed against the vendored OrcaSlicer
// catalog: Bambu X1C -- one nozzle behind an AMS -- has length 1; Snapmaker
// U1/Dual, genuine independent extruders, have length 2+). Default to 1 for
// any machine profile that doesn't have it, isn't an array, or is empty --
// never block on an unrecognized shape.
function slotCountFromMachineData(data: Record<string, unknown> | undefined): number {
  const nozzleDiameter = data?.nozzle_diameter
  return Array.isArray(nozzleDiameter) && nozzleDiameter.length > 0 ? nozzleDiameter.length : 1
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
  onUpdateLastSelection: (printerId: string | null, materialId: string | null) => Promise<unknown>
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
  // The selected machine's nozzle_diameter values (see parsedNozzleDiameters
  // above) -- used at slice time to work around a real catalog bug where a
  // mixed-diameter toolchanger's own process profile fails validation.
  const [nozzleDiameters, setNozzleDiameters] = useState<number[]>([])

  // Premade multi-plate/multi-material .3mf support: parsed once per upload
  // (see handleFileSelected), always present (a synthetic single implicit
  // plate for non-3mf uploads) so the plate picker/nozzle-assignment UI
  // below can render unconditionally off its shape.
  const [plateInfo, setPlateInfo] = useState<ThreeMfInspection | null>(null)
  const [plateIndex, setPlateIndex] = useState<number | null>(null)
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

  // Restoring the account's last-selected printer/material (see the mount
  // and material-list effects below) is an async, two-step process --
  // printers load first, then (if a printer was restored) its materials.
  // `restorationDone` gates the persist-on-change effect further down so it
  // can't fire with a half-restored state (printer set, material still
  // null) and overwrite the correct persisted material_id with null before
  // the second step finishes. `pendingLastMaterialId` is consumed exactly
  // once -- it's only meaningful for that first, restored materials fetch,
  // not any later manual printer switch.
  const [restorationDone, setRestorationDone] = useState(false)
  const [printersLoaded, setPrintersLoaded] = useState(false)
  const pendingLastMaterialId = useRef(authStatus.last_material_id)

  const [quickSettings, setQuickSettings] = useState<QuickSettingsValues>(defaultQuickSettings([]))
  const [advancedOverrides, setAdvancedOverrides] = useState<Record<string, string>>({})

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

  const viewJobGcode = useCallback((jobId: string) => {
    setViewedJobId(jobId)
    setViewMode('gcode')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])

  const backToModelView = useCallback(() => setViewMode('model'), [])

  const selectedPrinter = printers.find((p) => p.id === selectedPrinterId) ?? null
  const selectedMaterial = materials.find((m) => m.id === selectedMaterialId) ?? null

  // Collapsed by default once a saved printer/material is actually picked
  // (nothing left to configure), expanded otherwise. Only *changes* to the
  // selection force the collapse state -- toggling the <details> manually
  // afterward (e.g. to peek at or tweak a selected profile) sticks until
  // the selection changes again, rather than snapping back on every render.
  const [printerSettingsOpen, setPrinterSettingsOpen] = useState(!selectedPrinterId)
  const [quickSettingsOpen, setQuickSettingsOpen] = useState(!selectedMaterialId)
  useEffect(() => setPrinterSettingsOpen(!selectedPrinterId), [selectedPrinterId])
  useEffect(() => setQuickSettingsOpen(!selectedMaterialId), [selectedMaterialId])

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
        setQuickSettings(defaultQuickSettings(settingsSchema.settings))
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

  const applyMaterialProfile = useCallback((material: MaterialProfileRecord) => {
    setSelectedMaterialId(material.id)
    setQuickSettings((prev) => ({ ...prev, ...material.quick_settings }))
    setAdvancedOverrides(material.advanced_overrides)
    if (material.process_profile) setProcessName(material.process_profile)
    if (material.filament_profiles && material.filament_profiles.length > 0) {
      setFilamentSlots(
        material.filament_profiles.map((profile, i) => ({
          profile,
          color: material.filament_colors?.[i] ?? defaultSlotColor(i),
        })),
      )
    }
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

  const handleFileSelected = useCallback((selected: File) => {
    setFile(selected)
    setModelId(null)
    setUploadStatus('uploading')
    setScaleToastDismissed(false)
    setViewMode('model')
    setPlateInfo(null)
    setPlateIndex(null)
    uploadModel(selected)
      .then((res) => {
        setModelId(res.model_id)
        setUploadStatus('done')
        // Always fetch (even for non-3mf uploads): the endpoint always
        // returns a shape (a synthetic single implicit plate for anything
        // that isn't a .3mf with real plate metadata), so the plate
        // picker/nozzle-assignment UI never need a separate "is this even
        // a 3mf" branch.
        getModelPlates(res.model_id)
          .then(setPlateInfo)
          .catch(() => setPlateInfo(null))
      })
      .catch(() => setUploadStatus('error'))
  }, [])

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
    return loadSampleModel(sampleId)
      .then((res) => {
        setModelId(res.model_id)
        getModelPlates(res.model_id)
          .then(setPlateInfo)
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
  }, [])

  // Stable reference: Viewer's effect depends on this, and an inline arrow
  // function would make it re-run (tearing down/rebuilding the three.js
  // scene) on every unrelated App re-render.
  const handleDimensions = useCallback((dims: Dimensions | null) => setDimensions(dims), [])

  const fitScale =
    dimensions && bedSize && printerName ? computeFitScale(dimensions, bedSize) : null
  const showScaleToast = fitScale !== null && !scaleToastDismissed

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
          setProcessName(process)
          setFilamentSlots(buildFilamentSlots(slotCountFromMachineData(detail.data), filament))
          setBedSize(parseBedSize(detail.data))
          setNozzleDiameters(parsedNozzleDiameters(detail.data))
        })
        .catch(() => {
          setProcessName(firstOfKind('process'))
          setFilamentSlots(buildFilamentSlots(1, firstOfKind('filament')))
          setNozzleDiameters([])
        })
    },
    [vendor, profiles],
  )

  const handleVendorChange = useCallback((v: string) => {
    setVendor(v)
    setPrinterName('')
    setProcessName('')
    setFilamentSlots(buildFilamentSlots(1, ''))
    setBedSize(null)
    setNozzleDiameters([])
    setSelectedPrinterId(null)
    setViewMode('model')
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
          }))
        : buildFilamentSlots(1, ''),
    )
    setBedSize(
      printer.bed_width != null && printer.bed_depth != null && printer.bed_height != null
        ? { width: printer.bed_width, depth: printer.bed_depth, height: printer.bed_height }
        : null,
    )
    setScaleToastDismissed(false)
    setViewMode('model')
    setNozzleDiameters([])
    // The one piece a saved printer record doesn't snapshot itself: the
    // machine profile's actual nozzle_diameter values (only needed at
    // slice time, for the bridge_line_width safety clamp above) --
    // fetched fresh rather than blocking the otherwise-synchronous restore
    // above on it.
    getProfileDetail(printer.vendor, 'machine', printer.machine_profile)
      .then((detail) => setNozzleDiameters(parsedNozzleDiameters(detail.data)))
      .catch(() => setNozzleDiameters([]))
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
      // Restoring a material (if any) happens once this printer's
      // materials list loads -- see the effect above, which also marks
      // restorationDone when it settles.
    } else {
      setRestorationDone(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [printersLoaded])

  // Persists the current printer/material selection as the account's
  // default for next time -- but not until the initial restoration (above)
  // has fully settled, or this would race it: e.g. save (printerId, null)
  // right after the printer restores but before its material does, then
  // lose to a slower-finishing restore, permanently wiping the persisted
  // material_id.
  useEffect(() => {
    if (!restorationDone) return
    onUpdateLastSelection(selectedPrinterId, selectedMaterialId).catch(() => {})
  }, [selectedPrinterId, selectedMaterialId, restorationDone, onUpdateLastSelection])

  const handleSaveMaterial = useCallback(
    (name: string) => {
      if (!selectedPrinterId) return Promise.reject(new Error('Select a saved printer first'))
      return createMaterialProfile(selectedPrinterId, {
        name,
        quick_settings: quickSettings as unknown as Record<string, string>,
        advanced_overrides: advancedOverrides,
        process_profile: processName || null,
        filament_profiles: filamentSlots.map((s) => s.profile),
        filament_colors: filamentSlots.map((s) => s.color),
      }).then((material) => {
        setMaterials((prev) => [...prev, material])
        setSelectedMaterialId(material.id)
      })
    },
    [selectedPrinterId, quickSettings, advancedOverrides, processName, filamentSlots],
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
      quick_settings: quickSettings as unknown as Record<string, string>,
      advanced_overrides: advancedOverrides,
      process_profile: processName || null,
      filament_profiles: filamentSlots.map((s) => s.profile),
      filament_colors: filamentSlots.map((s) => s.color),
    }).then((material) => {
      setMaterials((prev) => prev.map((m) => (m.id === material.id ? material : m)))
    })
  }, [selectedPrinterId, selectedMaterialId, quickSettings, advancedOverrides, processName, filamentSlots])

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
  const showPlatePicker = (plateInfo?.plates.length ?? 0) > 1

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
      ),
    [modelId, printerName, processName, effectiveFilamentProfiles, plateIndex, quickSettings, advancedOverrides],
  )
  // Only a *successful* prior slice blocks re-slicing -- a failed job with
  // unchanged settings should still be retryable (e.g. a transient error).
  const alreadySliced = currentJob?.status === 'succeeded' && lastSlicedSignature === currentSignature
  const filamentSlotsFilled = filamentSlots.every((s) => s.profile)
  // A multi-plate file requires an explicit pick before slicing is enabled
  // -- there's no good "slice all of them" default once a specific plate
  // picker exists (see plan: pre-slice picker, not slice-everything).
  const plateChosenIfNeeded = !showPlatePicker || plateIndex !== null
  const canSlice =
    Boolean(modelId && printerName && processName && allRolesAssigned) &&
    plateChosenIfNeeded &&
    !alreadySliced

  const handleSlice = useCallback(() => {
    if (!modelId || !printerName || !processName || !allRolesAssigned || !plateChosenIfNeeded) return
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
    }
    // Only meaningful (and only worth sending) when support is actually on.
    if (quickSettings.enable_support === '1') {
      overrides.support_type = quickSettings.support_type
      overrides.support_buildplate_only = quickSettings.support_buildplate_only
    }
    // Confirmed via direct CLI testing: a mixed-diameter toolchanger's own
    // bundled process profile can fail slicing outright ("Bridge line
    // width must not exceed nozzle diameter") because its default
    // bridge_line_width was sized for its smaller nozzle but validated
    // against its largest -- clamp to the smallest configured nozzle
    // whenever there's genuine diameter variation, unless the user has
    // already set this explicitly via Advanced settings.
    const uniqueNozzleDiameters = new Set(nozzleDiameters)
    if (uniqueNozzleDiameters.size > 1 && !('bridge_line_width' in advancedOverrides)) {
      overrides.bridge_line_width = String(Math.min(...nozzleDiameters))
    }
    createJob({
      model_id: modelId,
      printer_profile: printerName,
      process_profile: processName,
      filament_profiles: effectiveFilamentProfiles,
      setting_overrides: overrides,
      plate_index: plateIndex ?? undefined,
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
    effectiveFilamentProfiles,
    plateIndex,
    quickSettings,
    advancedOverrides,
    nozzleDiameters,
    currentSignature,
  ])

  return (
    <div className="app">
      <header className="app-header">
        <h1>headless-orca</h1>
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
              <GcodeViewer jobId={viewedJobId} onBackToModel={backToModelView} />
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
              />
              <Viewer file={file} onDimensions={handleDimensions} bedSize={bedSize} colorTree={plateInfo?.color_tree} />
              {dimensions && (
                <>
                  <div className="dimensions-readout">
                    {dimensions.x.toFixed(1)} × {dimensions.y.toFixed(1)} × {dimensions.z.toFixed(1)} mm
                  </div>
                  <ScaleControls dimensions={dimensions} onApply={handleApplyScale} applying={scaling} />
                </>
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
          <h2>Printer &amp; material</h2>
          <SavedPrinters
            printers={printers}
            selectedPrinterId={selectedPrinterId}
            onSelectPrinter={applySavedPrinter}
            canSaveCurrent={Boolean(vendor && printerName && processName && filamentSlotsFilled)}
            onSavePrinter={handleSavePrinter}
            onUpdatePrinter={handleUpdatePrinter}
            onDeletePrinter={handleDeletePrinter}
            materials={materials}
            selectedMaterialId={selectedMaterialId}
            onSelectMaterial={applyMaterialProfile}
            onDeselectMaterial={handleDeselectMaterial}
            onSaveMaterial={handleSaveMaterial}
            onUpdateMaterial={handleUpdateMaterial}
            onRenameMaterial={handleRenameMaterial}
            onDuplicateMaterial={handleDuplicateMaterial}
            onDeleteMaterial={handleDeleteMaterial}
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
            />
          </details>

          <details
            className="settings-collapsible"
            open={quickSettingsOpen}
            onToggle={(e) => setQuickSettingsOpen(e.currentTarget.open)}
          >
            <summary>Quick settings{selectedMaterial ? ` (${selectedMaterial.name})` : ''}</summary>
            {filamentSlots.map((slot, i) => (
              <FilamentSelect
                key={i}
                profiles={profiles}
                vendor={vendor}
                filamentName={slot.profile}
                onFilamentChange={(name) => handleFilamentSlotChange(i, { profile: name })}
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
            ))}
            <QuickSettings schema={schema} values={quickSettings} onChange={handleQuickSettingsChange} />
          </details>

          <AdvancedSettings
            schema={schema}
            overrides={advancedOverrides}
            onChange={handleAdvancedOverridesChange}
            excludeKeys={QUICK_SETTING_KEYS}
          />

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

      {showScaleToast && dimensions && bedSize && fitScale !== null && (
        <div className="toast">
          <div className="toast-message">
            This model ({dimensions.x.toFixed(0)} × {dimensions.y.toFixed(0)} ×{' '}
            {dimensions.z.toFixed(0)} mm) is larger than {printerName}&rsquo;s build volume (
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
