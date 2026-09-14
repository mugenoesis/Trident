import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import {
  createJob,
  getJob,
  getProfileDetail,
  getSettingsSchema,
  listJobs,
  listProfiles,
  uploadModel,
} from './api'
import AdvancedSettings from './components/AdvancedSettings'
import JobPanel from './components/JobPanel'
import PrinterSelect from './components/PrinterSelect'
import QuickSettings, {
  QUICK_SETTING_KEYS,
  defaultQuickSettings,
  type QuickSettingsValues,
} from './components/QuickSettings'
import Uploader from './components/Uploader'
import Viewer from './components/Viewer'
import type { JobRecord, ProfileSummary, SettingDef } from './types'

const ACTIVE_STATUSES: JobRecord['status'][] = ['queued', 'running']
const POLL_INTERVAL_MS = 1500

export default function App() {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([])
  const [schema, setSchema] = useState<SettingDef[]>([])
  const [catalogError, setCatalogError] = useState<string | null>(null)

  const [file, setFile] = useState<File | null>(null)
  const [modelId, setModelId] = useState<string | null>(null)
  const [uploadStatus, setUploadStatus] = useState<'idle' | 'uploading' | 'done' | 'error'>('idle')

  const [vendor, setVendor] = useState('')
  const [printerName, setPrinterName] = useState('')
  const [processName, setProcessName] = useState('')
  const [filamentName, setFilamentName] = useState('')

  const [quickSettings, setQuickSettings] = useState<QuickSettingsValues>(defaultQuickSettings([]))
  const [advancedOverrides, setAdvancedOverrides] = useState<Record<string, string>>({})

  const [slicing, setSlicing] = useState(false)
  const [currentJob, setCurrentJob] = useState<JobRecord | null>(null)
  const [history, setHistory] = useState<JobRecord[]>([])

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
  }, [])

  const handleFileSelected = useCallback((selected: File) => {
    setFile(selected)
    setModelId(null)
    setUploadStatus('uploading')
    uploadModel(selected)
      .then((res) => {
        setModelId(res.model_id)
        setUploadStatus('done')
      })
      .catch(() => setUploadStatus('error'))
  }, [])

  // Picking a printer resets process/material to that machine's own
  // defaults (default_print_profile / default_filament_profile) --
  // matches how OrcaSlicer itself behaves when you switch printers.
  const handlePrinterChange = useCallback(
    (name: string) => {
      setPrinterName(name)
      setProcessName('')
      setFilamentName('')
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
  }, [])

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

  const canSlice = Boolean(modelId && printerName && processName && filamentName)

  const handleSlice = useCallback(() => {
    if (!modelId || !printerName || !processName || !filamentName) return
    setSlicing(true)
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
  }, [modelId, printerName, processName, filamentName, quickSettings, advancedOverrides])

  return (
    <div className="app">
      <header className="app-header">
        <h1>headless-orca</h1>
      </header>

      {catalogError && (
        <div className="banner-error">Failed to load printer/settings catalog: {catalogError}</div>
      )}

      <main className="app-main">
        <section className="panel panel-viewer">
          <Uploader onFileSelected={handleFileSelected} fileName={file?.name ?? null} uploadStatus={uploadStatus} />
          <Viewer file={file} />
        </section>

        <section className="panel panel-settings">
          <h2>Printer &amp; material</h2>
          <PrinterSelect
            profiles={profiles}
            vendor={vendor}
            printerName={printerName}
            processName={processName}
            filamentName={filamentName}
            onVendorChange={handleVendorChange}
            onPrinterChange={handlePrinterChange}
            onProcessChange={setProcessName}
            onFilamentChange={setFilamentName}
          />

          <h2>Quick settings</h2>
          <QuickSettings schema={schema} values={quickSettings} onChange={setQuickSettings} />

          <AdvancedSettings
            schema={schema}
            overrides={advancedOverrides}
            onChange={setAdvancedOverrides}
            excludeKeys={QUICK_SETTING_KEYS}
          />

          <JobPanel
            canSlice={canSlice}
            onSlice={handleSlice}
            slicing={slicing}
            currentJob={currentJob}
            history={history}
          />
        </section>
      </main>
    </div>
  )
}
