import { useRef, useState } from 'react';
import { buildFilamentSlots, type FilamentSlot } from '../appHelpers';
import type { RowMode } from '../beltLayout';
import type { BeltTransform } from '../beltTransform';
import { defaultQuickSettings, type QuickSettingsValues } from '../components/QuickSettings';
import type { ViewerHandle } from '../components/Viewer';
import type { BedSize, Dimensions } from '../dimensions';
import type {
	JobRecord,
	MaterialProfileRecord,
	MeshReport,
	Placement,
	PrinterRecord,
	ProfileSummary,
	SampleModelSummary,
	SettingDef,
	SettingsProfileRecord,
	ThreeMfInspection,
} from '../types';
import type { useAuth } from '../useAuth';

// Where MainApp's own props come in.
export interface MainAppProps {
	authStatus: NonNullable<ReturnType<typeof useAuth>['status']>;
	onSwitchToMulti: (username: string, password: string) => Promise<unknown>;
	onSwitchToSingle: () => Promise<unknown>;
	onCreateUser: (username: string, password: string) => Promise<unknown>;
	onLogout: () => Promise<unknown>;
	onUpdateLastSelection: (printerId: string | null, materialId: string | null, settingsProfileId: string | null) => Promise<unknown>;
}

// Every piece of state the main screen keeps, in one place; the hooks next to this file hold the logic that works on it.
export function useAppState({ authStatus }: Pick<MainAppProps, 'authStatus'>) {
	const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
	const [importOpen, setImportOpen] = useState(false);
	const [exportOpen, setExportOpen] = useState(false);
	// The "New printer" / "Edit printer" form, and a printer just saved that is to be selected once the list has it.
	const [printerDialog, setPrinterDialog] = useState<{ mode: 'create' | 'edit' } | null>(null);
	const [pendingPrinter, setPendingPrinter] = useState<string | null>(null);
	// The "Rotate and move" window (RotateMoveDialog).
	const [rotateMoveOpen, setRotateMoveOpen] = useState(false);
	// The "New material" / "Edit material" form, opened from a material slot.
	const [materialDialog, setMaterialDialog] = useState<{
		mode: 'create' | 'edit';
		slot: number;
		base: { vendor: string; name: string };
	} | null>(null);
	// Build plates the selected material(s) can print on (null = no restriction
	// known), and the printer's own default plate.
	const [allowedBedTypes, setAllowedBedTypes] = useState<string[] | null>(null);
	const [printerDefaultBed, setPrinterDefaultBed] = useState<string | null>(null);
	// Where the user put the model on the plate (Position panel); null = the
	// slicer's own default spot.
	const [placement, setPlacement] = useState<Placement | null>(null);
	// How many copies of the (selected) model to print.
	const [copies, setCopies] = useState(1);
	// The job whose "line them up instead?" question was already answered, and
	// whether to slice again as soon as line-up is switched on.
	const [lineUpAnsweredFor, setLineUpAnsweredFor] = useState<string | null>(null);
	const [retryAfterLineUp, setRetryAfterLineUp] = useState(false);
	const [positionBusy, setPositionBusy] = useState<'orient' | 'arrange' | null>(null);
	const [schema, setSchema] = useState<SettingDef[]>([]);
	const [catalogError, setCatalogError] = useState<string | null>(null);
	const [sampleModels, setSampleModels] = useState<SampleModelSummary[]>([]);

	const [file, setFile] = useState<File | null>(null);
	const [modelId, setModelId] = useState<string | null>(null);
	const [uploadStatus, setUploadStatus] = useState<'idle' | 'uploading' | 'done' | 'error'>('idle');
	const [dimensions, setDimensions] = useState<Dimensions | null>(null);

	const [vendor, setVendor] = useState('');
	const [printerName, setPrinterName] = useState('');
	const [processName, setProcessName] = useState('');
	const [filamentSlots, setFilamentSlots] = useState<FilamentSlot[]>(buildFilamentSlots(1, ''));
	const [bedSize, setBedSize] = useState<BedSize | null>(null);
	// The selected machine's own nozzle_diameter/nozzle_type values (see
	// parsedNozzleDiameters/parsedNozzleTypes above) -- used only to seed
	// sensible defaults (freshly built/added slots, the global control below)
	// and to clamp bridge_line_width; never sent to OrcaSlicer directly.
	const [nozzleDiameters, setNozzleDiameters] = useState<number[]>([]);
	const [nozzleTypes, setNozzleTypes] = useState<string[]>([]);
	const [globalNozzleDiameter, setGlobalNozzleDiameter] = useState('');
	const [globalNozzleType, setGlobalNozzleType] = useState('undefine');

	// Premade multi-plate/multi-material .3mf support: parsed once per upload
	// (see handleFileSelected), always present (a synthetic single implicit
	// plate for non-3mf uploads) so the plate picker/nozzle-assignment UI
	// below can render unconditionally off its shape.
	const [plateInfo, setPlateInfo] = useState<ThreeMfInspection | null>(null);
	const [plateIndex, setPlateIndex] = useState<number | null>(null);
	// Which objects of a multi-object .3mf to leave out of the print, and how
	// a belt printer lines the rest up (ObjectPicker). Indices are
	// ObjectInfo.index, i.e. build-item order.
	const [excludedObjects, setExcludedObjects] = useState<Set<number>>(new Set());
	const [beltLineUp, setBeltLineUp] = useState(true);
	const [beltOrder, setBeltOrder] = useState<number[]>([]);
	const [beltGapMm, setBeltGapMm] = useState(10);
	// A multi-plate file on a belt printer: each plate as a block one after another (the default), or every object in one row.
	const [beltRowMode, setBeltRowMode] = useState<RowMode>('plates');
	const [objectThumbs, setObjectThumbs] = useState<Record<number, string>>({});
	const [objectPickerOpen, setObjectPickerOpen] = useState(false);
	// Result of the upload-time STL check, and whether its notice was dismissed.
	const [meshReport, setMeshReport] = useState<MeshReport | null>(null);
	const [meshToastDismissed, setMeshToastDismissed] = useState(false);
	// Which of the printer's configured filamentSlots (by index) supplies
	// each "role" (color/material) the uploaded file itself needs -- see
	// fileRoles below. null means "not chosen yet". Sending a mismatched
	// filament count relative to what the file actually needs (previously:
	// always all of filamentSlots, regardless of file need) is a confirmed
	// OrcaSlicer CLI crash trigger (exit code -11) against a real downloaded
	// multi-color model whose file only needed 2 roles but got 4 filaments
	// -- this explicit per-role mapping is what keeps the sent count exactly
	// matching what the file needs, chosen from real catalog-backed slots.
	const [roleNozzleAssignments, setRoleNozzleAssignments] = useState<(number | null)[]>([0]);

	const [scaleToastDismissed, setScaleToastDismissed] = useState(false);
	const [scaling, setScaling] = useState(false);

	const [printers, setPrinters] = useState<PrinterRecord[]>([]);
	const [selectedPrinterId, setSelectedPrinterId] = useState<string | null>(null);
	const [materials, setMaterials] = useState<MaterialProfileRecord[]>([]);
	const [selectedMaterialId, setSelectedMaterialId] = useState<string | null>(null);
	// Independent from materials -- see SettingsProfileRecord: print-quality
	// settings only, saved/loaded separately so the same materials can be
	// reused across quality presets and vice versa.
	const [settingsProfiles, setSettingsProfiles] = useState<SettingsProfileRecord[]>([]);
	const [selectedSettingsProfileId, setSelectedSettingsProfileId] = useState<string | null>(null);

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
	const [restorationDone, setRestorationDone] = useState(false);
	const [settingsRestorationDone, setSettingsRestorationDone] = useState(false);
	const [printersLoaded, setPrintersLoaded] = useState(false);
	const pendingLastMaterialId = useRef(authStatus.last_material_id);
	const pendingLastSettingsProfileId = useRef(authStatus.last_settings_profile_id);
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
	const appliedSettingsProfileRef = useRef(false);
	// Lets handleSlice grab a snapshot of the 3D preview at the moment
	// slicing starts, to embed into the gcode and this app's own job
	// thumbnail (see api/app/gcode_thumbnail.py) -- the engine itself never
	// renders one in CLI mode.
	const viewerRef = useRef<ViewerHandle>(null);

	const [quickSettings, setQuickSettings] = useState<QuickSettingsValues>(defaultQuickSettings([]));
	const [advancedOverrides, setAdvancedOverrides] = useState<Record<string, string>>({});

	const [slicing, setSlicing] = useState(false);
	const [currentJob, setCurrentJob] = useState<JobRecord | null>(null);
	const [history, setHistory] = useState<JobRecord[]>([]);
	// Signature of the settings the current/last job was actually sliced
	// with, so a repeat click of "Slice" with nothing changed can be a no-op
	// instead of queuing an identical job.
	const [lastSlicedSignature, setLastSlicedSignature] = useState<string | null>(null);

	// Which job's G-code the viewer panel shows, and whether it's showing
	// that at all right now (vs. the 3D model). Separate from currentJob:
	// a history item can be previewed independently of whatever's currently
	// slicing.
	const [viewedJobId, setViewedJobId] = useState<string | null>(null);
	const [viewMode, setViewMode] = useState<'model' | 'gcode'>('model');

	// The gcode viewer's belt back-transform (see beltTransform.ts) must match
	// whichever printer THIS job was actually sliced with, not whatever the
	// printer dropdown currently has selected (`bedSize` below) -- those two
	// can disagree the moment a job from history is reopened, or the page
	// reloads, without reselecting the same printer. Resolved independently
	// here from the job's own recorded printer_profile so the viewer is
	// correct regardless of ambient UI selection state.
	const [viewedJobBeltTransform, setViewedJobBeltTransform] = useState<BeltTransform | null>(null);

	// Collapsed by default once a saved printer/material/settings profile is
	// actually picked (nothing left to configure), expanded otherwise. Only
	// *changes* to the selection force the collapse state -- toggling the
	// <details> manually afterward (e.g. to peek at or tweak a selected
	// profile) sticks until the selection changes again, rather than
	// snapping back on every render.
	const [printerSettingsOpen, setPrinterSettingsOpen] = useState(!selectedPrinterId);
	const [materialSectionOpen, setMaterialSectionOpen] = useState(!selectedMaterialId);
	const [settingsSectionOpen, setSettingsSectionOpen] = useState(!selectedSettingsProfileId);

	// Read via refs (not state) inside applyMaterialProfile below, so that
	// callback's identity stays stable regardless of when the catalog's own
	// nozzle data happens to arrive -- applySavedPrinter fetches it
	// asynchronously *after* already setting selectedPrinterId, and this
	// callback's identity is itself a dependency of the materials-fetch
	// effect further down; if it changed later (state instead of a ref), that
	// effect would re-fire, refetch materials, and wipe out a just-restored
	// material selection out from under the user.
	const nozzleDiametersRef = useRef<number[]>([]);
	const nozzleTypesRef = useRef<string[]>([]);

	// Poll the active job until it leaves queued/running.
	const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
	return {
		profiles,
		setProfiles,
		importOpen,
		setImportOpen,
		exportOpen,
		setExportOpen,
		printerDialog,
		setPrinterDialog,
		pendingPrinter,
		setPendingPrinter,
		rotateMoveOpen,
		setRotateMoveOpen,
		materialDialog,
		setMaterialDialog,
		allowedBedTypes,
		setAllowedBedTypes,
		printerDefaultBed,
		setPrinterDefaultBed,
		placement,
		setPlacement,
		copies,
		setCopies,
		lineUpAnsweredFor,
		setLineUpAnsweredFor,
		retryAfterLineUp,
		setRetryAfterLineUp,
		positionBusy,
		setPositionBusy,
		schema,
		setSchema,
		catalogError,
		setCatalogError,
		sampleModels,
		setSampleModels,
		file,
		setFile,
		modelId,
		setModelId,
		uploadStatus,
		setUploadStatus,
		dimensions,
		setDimensions,
		vendor,
		setVendor,
		printerName,
		setPrinterName,
		processName,
		setProcessName,
		filamentSlots,
		setFilamentSlots,
		bedSize,
		setBedSize,
		nozzleDiameters,
		setNozzleDiameters,
		nozzleTypes,
		setNozzleTypes,
		globalNozzleDiameter,
		setGlobalNozzleDiameter,
		globalNozzleType,
		setGlobalNozzleType,
		plateInfo,
		setPlateInfo,
		plateIndex,
		setPlateIndex,
		excludedObjects,
		setExcludedObjects,
		beltLineUp,
		setBeltLineUp,
		beltOrder,
		setBeltOrder,
		beltGapMm,
		setBeltGapMm,
		beltRowMode,
		setBeltRowMode,
		objectThumbs,
		setObjectThumbs,
		objectPickerOpen,
		setObjectPickerOpen,
		meshReport,
		setMeshReport,
		meshToastDismissed,
		setMeshToastDismissed,
		roleNozzleAssignments,
		setRoleNozzleAssignments,
		scaleToastDismissed,
		setScaleToastDismissed,
		scaling,
		setScaling,
		printers,
		setPrinters,
		selectedPrinterId,
		setSelectedPrinterId,
		materials,
		setMaterials,
		selectedMaterialId,
		setSelectedMaterialId,
		settingsProfiles,
		setSettingsProfiles,
		selectedSettingsProfileId,
		setSelectedSettingsProfileId,
		restorationDone,
		setRestorationDone,
		settingsRestorationDone,
		setSettingsRestorationDone,
		printersLoaded,
		setPrintersLoaded,
		pendingLastMaterialId,
		pendingLastSettingsProfileId,
		appliedSettingsProfileRef,
		viewerRef,
		quickSettings,
		setQuickSettings,
		advancedOverrides,
		setAdvancedOverrides,
		slicing,
		setSlicing,
		currentJob,
		setCurrentJob,
		history,
		setHistory,
		lastSlicedSignature,
		setLastSlicedSignature,
		viewedJobId,
		setViewedJobId,
		viewMode,
		setViewMode,
		viewedJobBeltTransform,
		setViewedJobBeltTransform,
		printerSettingsOpen,
		setPrinterSettingsOpen,
		materialSectionOpen,
		setMaterialSectionOpen,
		settingsSectionOpen,
		setSettingsSectionOpen,
		nozzleDiametersRef,
		nozzleTypesRef,
		pollRef,
	};
}

export type AppState = ReturnType<typeof useAppState>;
