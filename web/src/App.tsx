import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import {
  createJob,
  createMaterialProfile,
  createPrinter,
  deleteJob,
  deleteMaterialProfile,
  deletePrinter,
  duplicateMaterialProfile,
  getJob,
  getProfileDetail,
  getSettingsSchema,
  listJobs,
  listMaterialProfiles,
  listPrinters,
  listProfiles,
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
  SettingDef,
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
  filamentName: string,
  quickSettings: QuickSettingsValues,
  advancedOverrides: Record<string, string>,
): string {
  return JSON.stringify({
    modelId,
    printerName,
    processName,
    filamentName,
    quickSettings: sortedEntries(quickSettings as unknown as Record<string, unknown>),
    advancedOverrides: sortedEntries(advancedOverrides),
  })
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

  const [file, setFile] = useState<File | null>(null)
  const [modelId, setModelId] = useState<string | null>(null)
  const [uploadStatus, setUploadStatus] = useState<'idle' | 'uploading' | 'done' | 'error'>('idle')
  const [dimensions, setDimensions] = useState<Dimensions | null>(null)

  const [vendor, setVendor] = useState('')
  const [printerName, setPrinterName] = useState('')
  const [processName, setProcessName] = useState('')
  const [filamentName, setFilamentName] = useState('')
  const [bedSize, setBedSize] = useState<BedSize | null>(null)

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
  }, [])

  const applyMaterialProfile = useCallback((material: MaterialProfileRecord) => {
    setSelectedMaterialId(material.id)
    setQuickSettings((prev) => ({ ...prev, ...material.quick_settings }))
    setAdvancedOverrides(material.advanced_overrides)
    if (material.process_profile) setProcessName(material.process_profile)
    if (material.filament_profile) setFilamentName(material.filament_profile)
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
    uploadModel(selected)
      .then((res) => {
        setModelId(res.model_id)
        setUploadStatus('done')
      })
      .catch(() => setUploadStatus('error'))
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
      setFilamentName('')
      setBedSize(null)
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
        return namedForPrinter?.name ?? inVendor[0]?.name ?? ''
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
          setFilamentName(filament)
          setBedSize(parseBedSize(detail.data))
        })
        .catch(() => {
          setProcessName(firstOfKind('process'))
          setFilamentName(firstOfKind('filament'))
        })
    },
    [vendor, profiles],
  )

  const handleVendorChange = useCallback((v: string) => {
    setVendor(v)
    setPrinterName('')
    setProcessName('')
    setFilamentName('')
    setBedSize(null)
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

  const handleFilamentChange = useCallback((name: string) => {
    setFilamentName(name)
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
    setFilamentName(printer.filament_profile)
    setBedSize(
      printer.bed_width != null && printer.bed_depth != null && printer.bed_height != null
        ? { width: printer.bed_width, depth: printer.bed_depth, height: printer.bed_height }
        : null,
    )
    setScaleToastDismissed(false)
    setViewMode('model')
  }, [])

  const handleSavePrinter = useCallback(
    (name: string, connection: PrinterConnection) => {
      return createPrinter({
        name,
        vendor,
        machine_profile: printerName,
        process_profile: processName,
        filament_profile: filamentName,
        bed_width: bedSize?.width ?? null,
        bed_depth: bedSize?.depth ?? null,
        bed_height: bedSize?.height ?? null,
        ...connection,
      }).then((printer) => {
        setPrinters((prev) => [...prev, printer])
        setSelectedPrinterId(printer.id)
      })
    },
    [vendor, printerName, processName, filamentName, bedSize],
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
        filament_profile: filamentName || null,
      }).then((material) => {
        setMaterials((prev) => [...prev, material])
        setSelectedMaterialId(material.id)
      })
    },
    [selectedPrinterId, quickSettings, advancedOverrides, processName, filamentName],
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
      filament_profile: filamentName || null,
    }).then((material) => {
      setMaterials((prev) => prev.map((m) => (m.id === material.id ? material : m)))
    })
  }, [selectedPrinterId, selectedMaterialId, quickSettings, advancedOverrides, processName, filamentName])

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

  const currentSignature = useMemo(
    () => computeSliceSignature(modelId, printerName, processName, filamentName, quickSettings, advancedOverrides),
    [modelId, printerName, processName, filamentName, quickSettings, advancedOverrides],
  )
  // Only a *successful* prior slice blocks re-slicing -- a failed job with
  // unchanged settings should still be retryable (e.g. a transient error).
  const alreadySliced = currentJob?.status === 'succeeded' && lastSlicedSignature === currentSignature
  const canSlice = Boolean(modelId && printerName && processName && filamentName) && !alreadySliced

  const handleSlice = useCallback(() => {
    if (!modelId || !printerName || !processName || !filamentName) return
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
    createJob({
      model_id: modelId,
      printer_profile: printerName,
      process_profile: processName,
      filament_profiles: [filamentName],
      setting_overrides: overrides,
    })
      .then(setCurrentJob)
      .catch((err: Error) => {
        setSlicing(false)
        alert(`Failed to start slicing job: ${err.message}`)
      })
  }, [modelId, printerName, processName, filamentName, quickSettings, advancedOverrides, currentSignature])

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
              <Viewer file={file} onDimensions={handleDimensions} bedSize={bedSize} />
              {dimensions && (
                <>
                  <div className="dimensions-readout">
                    {dimensions.x.toFixed(1)} × {dimensions.y.toFixed(1)} × {dimensions.z.toFixed(1)} mm
                  </div>
                  <ScaleControls dimensions={dimensions} onApply={handleApplyScale} applying={scaling} />
                </>
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
            canSaveCurrent={Boolean(vendor && printerName && processName && filamentName)}
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
            <FilamentSelect
              profiles={profiles}
              vendor={vendor}
              filamentName={filamentName}
              onFilamentChange={handleFilamentChange}
            />
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
