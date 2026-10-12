import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPrinterProfile, getPrinterKeys, getProfileDetail, getStoredPrinter, updatePrinterProfile } from '../api';
import { settingText } from '../settingText';
import type { PrinterForm, ProfileSummary, SettingDef } from '../types';
import AdvancedSettingsTab from './AdvancedSettingsTab';

// A belt printer with no limit is drawn this long (the same length the server writes for it).
const ENDLESS_BELT_LENGTH_MM = 2000;
const IMPORTED_VENDOR = 'My profiles';
const GENERIC_VENDOR = 'Custom';

interface PrinterDialogProps {
	// create: a new printer, by default a copy of `current`; edit: change the user's own printer `current`.
	mode: 'create' | 'edit';
	current: { vendor: string; name: string } | null;
	profiles: ProfileSummary[];
	schema: SettingDef[];
	onClose: () => void;
	onSaved: (name: string) => void;
}

type Tab = 'basics' | 'advanced';

// Everything on the Basics tab, as text so a box can be cleared and retyped.
interface Fields {
	flavour: string;
	shape: 'rectangle' | 'circle';
	width: string;
	depth: string;
	height: string;
	originX: string;
	originY: string;
	originCentre: boolean;
	belt: boolean;
	endless: boolean;
	beltLength: string;
	beltAngle: string;
	nozzle: string;
	nozzleType: string;
	start: string;
	end: string;
	maxSpeed: string;
	maxAccel: string;
	retractLen: string;
	retractSpeed: string;
	zHop: string;
	auxFan: boolean;
	process: string;
	material: string;
}

const EMPTY: Fields = {
	flavour: 'marlin2',
	shape: 'rectangle',
	width: '220',
	depth: '220',
	height: '250',
	originX: '0',
	originY: '0',
	originCentre: false,
	belt: false,
	endless: true,
	beltLength: '500',
	beltAngle: '45',
	nozzle: '0.4',
	nozzleType: '',
	start: '',
	end: '',
	maxSpeed: '',
	maxAccel: '',
	retractLen: '',
	retractSpeed: '',
	zHop: '',
	auxFan: false,
	process: '',
	material: '',
};

// A preset value as one text: the first entry of a list (one per extruder variant), or the value itself.
function first(data: Record<string, unknown>, key: string): string {
	const v = data[key];
	const x = Array.isArray(v) ? v[0] : v;
	return typeof x === 'string' || typeof x === 'number' ? String(x) : '';
}

const round = (n: number) => String(Math.round(n * 100) / 100);

// The bed a preset describes, from its "XxY" corner list.
function readBed(data: Record<string, unknown>): Partial<Fields> {
	const area = Array.isArray(data.printable_area) ? data.printable_area : [];
	const points = area.map((p) => String(p).split('x').map(Number)).filter((p) => p.length === 2 && p.every((n) => Number.isFinite(n)));
	if (points.length < 3) return {};
	const xs = points.map((p) => p[0]);
	const ys = points.map((p) => p[1]);
	const x0 = Math.min(...xs);
	const y0 = Math.min(...ys);
	const width = Math.max(...xs) - x0;
	const depth = Math.max(...ys) - y0;
	// A circle is a polygon with many corners, all the same distance from the middle.
	const cx = x0 + width / 2;
	const cy = y0 + depth / 2;
	const radii = points.map((p) => Math.hypot(p[0] - cx, p[1] - cy));
	const round_ = points.length > 8 && Math.max(...radii) - Math.min(...radii) < 0.02 * Math.max(...radii);
	const centred = Math.abs(cx) < 0.5 && Math.abs(cy) < 0.5;
	return {
		shape: round_ ? 'circle' : 'rectangle',
		width: round(width),
		depth: round(depth),
		originCentre: centred,
		originX: centred ? '0' : round(x0),
		originY: centred ? '0' : round(y0),
	};
}

// A preset stores a switch as "1", 1 or true.
const isOn = (v: unknown) => v === '1' || v === 1 || v === true;

// Basics fields that are a preset key's first value as text.
const TEXT_FIELDS: [keyof Fields, string][] = [
	['flavour', 'gcode_flavor'],
	['height', 'printable_height'],
	['beltAngle', 'belt_slice_rotation_angle'],
	['nozzle', 'nozzle_diameter'],
	['nozzleType', 'nozzle_type'],
	['maxSpeed', 'machine_max_speed_x'],
	['maxAccel', 'machine_max_acceleration_extruding'],
	['retractLen', 'retraction_length'],
	['retractSpeed', 'retraction_speed'],
	['zHop', 'z_hop'],
	['process', 'default_print_profile'],
	['material', 'default_filament_profile'],
];

// The Basics fields a resolved printer preset gives.
function fieldsFrom(data: Record<string, unknown>): Partial<Fields> {
	const out: Partial<Fields> = { ...readBed(data) };
	out.belt = isOn(data.belt_printer);
	if (out.belt) {
		out.endless = isOn(data.belt_printer_infinite_y);
		if (out.depth && !out.endless) out.beltLength = out.depth;
	}
	for (const [field, key] of TEXT_FIELDS) {
		const v = first(data, key);
		if (v !== '') (out as Record<string, string>)[field] = v;
	}
	out.start = typeof data.machine_start_gcode === 'string' ? data.machine_start_gcode : '';
	out.end = typeof data.machine_end_gcode === 'string' ? data.machine_end_gcode : '';
	out.auxFan = isOn(data.auxiliary_fan);
	return out;
}

/** The fields with `next` laid over them, leaving alone what the user has typed in when keepTouched is set. */
function mergeFields(prev: Fields, next: Partial<Fields>, touched: Set<string>, keepTouched: boolean): Fields {
	const merged = { ...prev } as Record<string, unknown>;
	for (const [k, v] of Object.entries(next)) {
		if (!(keepTouched && touched.has(k))) merged[k] = v;
	}
	return merged as unknown as Fields;
}

/** The settings a stored printer holds beyond the form's own: the slicer's keys, as text. */
function extraSettings(stored: Record<string, unknown>, keys: string[]): Record<string, string> {
	const allowed = new Set(keys);
	const extras: Record<string, string> = {};
	for (const [k, v] of Object.entries(stored)) if (allowed.has(k)) extras[k] = settingText(v);
	return extras;
}

/** The drop-down choices for a kind of profile: the current one's vendor and the user's own, else the first 200. */
function profileChoices(profiles: ProfileSummary[], kind: string, selected: string): ProfileSummary[] {
	const vendorOf = profiles.find((p) => p.kind === kind && p.name === selected)?.vendor;
	const list = profiles.filter((p) => p.kind === kind && (p.vendor === vendorOf || p.vendor === IMPORTED_VENDOR));
	return list.length > 0 ? list : profiles.filter((p) => p.kind === kind).slice(0, 200);
}

/** The name a setting's value goes by in the menu. */
function labelFor(def: SettingDef | undefined, value: string): string {
	const at = def?.enum_values?.indexOf(value) ?? -1;
	return at >= 0 && def?.enum_labels?.[at] ? def.enum_labels[at] : value;
}

const optionalNumber = (value: string, label: string): number | undefined =>
	value.trim() === '' ? undefined : requiredNumber(value, label);

function requiredNumber(value: string, label: string): number {
	const n = Number(value);
	if (value.trim() === '' || !Number.isFinite(n)) throw new Error(`${label} must be a number`);
	return n;
}

/** The request for the server from the Basics fields; throws a readable error for a field that is not a number. */
function buildPrinterForm(f: Fields, name: string, baseName: string | null | undefined, advanced: Record<string, string>): PrinterForm {
	const form: PrinterForm = {
		name,
		base_name: baseName,
		gcode_flavor: f.flavour,
		shape: f.shape,
		width: requiredNumber(f.width, 'Width'),
		height: requiredNumber(f.height, 'Maximum height'),
		origin_x: requiredNumber(f.originX || '0', 'Origin X offset'),
		origin_y: requiredNumber(f.originY || '0', 'Origin Y offset'),
		origin_centre: f.originCentre,
		belt: f.belt,
		belt_endless: f.endless,
		nozzle_diameter: requiredNumber(f.nozzle, 'Nozzle diameter'),
		nozzle_type: f.nozzleType || undefined,
		start_gcode: f.start,
		end_gcode: f.end,
		max_speed: optionalNumber(f.maxSpeed, 'Maximum speed'),
		max_acceleration: optionalNumber(f.maxAccel, 'Maximum acceleration'),
		retraction_length: optionalNumber(f.retractLen, 'Retraction length'),
		retraction_speed: optionalNumber(f.retractSpeed, 'Retraction speed'),
		z_hop: optionalNumber(f.zHop, 'Z hop'),
		auxiliary_fan: f.auxFan,
		default_process: f.process || undefined,
		default_material: f.material || undefined,
		advanced,
	};
	if (f.belt) {
		form.belt_angle = requiredNumber(f.beltAngle, 'Belt angle');
		if (!f.endless) form.belt_length = requiredNumber(f.beltLength, 'Belt length');
	} else if (f.shape === 'rectangle') {
		form.depth = requiredNumber(f.depth, 'Depth');
	}
	return form;
}

// "MyMarlin 0.4 nozzle" and friends: the slicer's generic printer for a firmware (or a belt printer).
function genericName(flavour: string, belt: boolean): string {
	if (belt) return 'MyBeltPrinter 0.4 nozzle';
	const by: Record<string, string> = {
		klipper: 'MyKlipper 0.4 nozzle',
		reprapfirmware: 'MyRRF 0.4 nozzle',
		repetier: 'MyRepetier 0.4 nozzle',
	};
	return by[flavour] ?? 'MyMarlin 0.4 nozzle';
}

function message(err: Error): string {
	return err.message.replace(/^\d{3}\s+/, '');
}

// How deep the bed is, in mm: a belt's length (or the drawn length of an endless one), a circle's diameter, or the depth.
function bedDepth(f: Fields): number {
	if (f.belt) return f.endless ? ENDLESS_BELT_LENGTH_MM : Number(f.beltLength);
	return f.shape === 'circle' ? Number(f.width) : Number(f.depth);
}

// Where the bed sits in the drawing and where the machine's zero is, or null when the size is not usable.
function bedLayout(f: Fields) {
	const width = Number(f.width);
	const depth = bedDepth(f);
	if (!(width > 0) || !(depth > 0)) return null;
	// A long belt is drawn at most three times as long as it is wide, with its end faded.
	const drawDepth = f.belt ? Math.min(depth, width * 3) : depth;
	const box = { w: 150, h: 110 };
	const scale = Math.min(box.w / width, box.h / drawDepth);
	const w = width * scale;
	const h = drawDepth * scale;
	const left = 20 + (box.w - w) / 2;
	const top = 14 + (box.h - h);
	const x0 = f.originCentre ? -width / 2 : Number(f.originX) || 0;
	const y0 = f.originCentre ? -(f.shape === 'circle' ? width : depth) / 2 : Number(f.originY) || 0;
	const zeroX = left + (-x0 / width) * w;
	const zeroY = top + h - (-y0 / (f.belt ? drawDepth : f.shape === 'circle' ? width : depth)) * h;
	const label = f.belt && f.endless ? `${round(width)} mm wide, no length limit` : `${round(width)} × ${round(depth)} mm`;
	return { w, h, left, top, zeroX, zeroY, label };
}

// The bed drawn to scale, with the machine's zero marked.
function BedDrawing({ f }: { f: Fields }) {
	const layout = bedLayout(f);
	if (!layout) return null;
	const { w, h, left, top, zeroX, zeroY, label } = layout;
	return (
		<svg viewBox="0 0 190 150" role="img" aria-label={`The bed to scale: ${label}`} className="bed-drawing">
			{f.shape === 'circle' && !f.belt ? (
				<ellipse cx={left + w / 2} cy={top + h / 2} rx={w / 2} ry={h / 2} fill="#1d2228" stroke="#6b7480" />
			) : (
				<rect
					x={left}
					y={top}
					width={w}
					height={h}
					fill="#1d2228"
					stroke="#6b7480"
					strokeDasharray={f.belt && f.endless ? '0' : undefined}
				/>
			)}
			{f.belt && f.endless && <rect x={left} y={top} width={w} height={Math.min(18, h)} fill="url(#fade)" />}
			<defs>
				<linearGradient id="fade" x1="0" x2="0" y1="0" y2="1">
					<stop offset="0" stopColor="#14171b" />
					<stop offset="1" stopColor="#14171b" stopOpacity="0" />
				</linearGradient>
			</defs>
			<circle cx={zeroX} cy={zeroY} r="4" fill="#dba74a" />
			<text x={zeroX + 6} y={zeroY - 5} fill="#dba74a" fontSize="9">
				0, 0
			</text>
			<text x="95" y="142" fill="#9aa2ad" fontSize="9" textAnchor="middle">
				{label}
			</text>
		</svg>
	);
}

function initialName(mode: 'create' | 'edit', current: { name: string } | null): string {
	if (!current) return '';
	return mode === 'edit' ? current.name : `${current.name} (custom)`;
}

function initialBaseKey(mode: 'create' | 'edit', current: { name: string } | null): string {
	if (mode === 'edit') return 'edit';
	return current ? 'selected' : 'nothing';
}

// Where each choice in "Start from" comes from.
function startOptionsFor(profiles: ProfileSummary[]) {
	const generics = profiles
		.filter((p) => p.kind === 'machine' && p.vendor === GENERIC_VENDOR && p.name.startsWith('My') && p.name.endsWith('0.4 nozzle'))
		.sort((a, b) => a.name.localeCompare(b.name));
	const mine = profiles.filter((p) => p.kind === 'machine' && p.vendor === IMPORTED_VENDOR);
	return { generics, mine };
}

type SetField = <K extends keyof Fields>(key: K, value: Fields[K]) => void;

// The bed's shape, size and origin, whether it is a belt, and the drawing of it.
function BuildPlateSection({ f, set, onBelt }: { f: Fields; set: SetField; onBelt: (belt: boolean) => void }) {
	return (
		<>
			<h3 className="material-section">Build plate</h3>
			<div className="printer-bed-row">
				<div className="printer-bed-fields">
					<div className="material-grid">
						<label>
							Shape
							<select value={f.shape} disabled={f.belt} onChange={(e) => set('shape', e.target.value as Fields['shape'])}>
								<option value="rectangle">Rectangle</option>
								<option value="circle">Circle</option>
							</select>
						</label>
						<label>
							Max height (Z, mm)
							<input type="number" step="1" value={f.height} onChange={(e) => set('height', e.target.value)} />
						</label>
					</div>
					<div className="material-grid">
						<label>
							{f.shape === 'circle' && !f.belt ? 'Diameter (mm)' : 'Width (X, mm)'}
							<input type="number" step="1" value={f.width} onChange={(e) => set('width', e.target.value)} />
						</label>
						{!f.belt && f.shape === 'rectangle' && (
							<label>
								Depth (Y, mm)
								<input type="number" step="1" value={f.depth} onChange={(e) => set('depth', e.target.value)} />
							</label>
						)}
					</div>
					<div className="material-grid">
						<label>
							Origin X offset (mm)
							<input type="number" step="1" value={f.originX} disabled={f.originCentre} onChange={(e) => set('originX', e.target.value)} />
						</label>
						<label>
							Origin Y offset (mm)
							<input type="number" step="1" value={f.originY} disabled={f.originCentre} onChange={(e) => set('originY', e.target.value)} />
						</label>
					</div>
					<label className="checkbox-label">
						<input type="checkbox" checked={f.originCentre} onChange={(e) => set('originCentre', e.target.checked)} />
						The origin is at the centre of the bed
					</label>
					<label className="checkbox-label">
						<input type="checkbox" checked={f.belt} onChange={(e) => onBelt(e.target.checked)} />
						This is a belt (conveyor) printer
					</label>
					{f.belt && (
						<div className="printer-belt">
							<div className="material-grid">
								<label>
									Belt angle (°)
									<input type="number" step="1" value={f.beltAngle} onChange={(e) => set('beltAngle', e.target.value)} />
								</label>
							</div>
							<label className="checkbox-label">
								<input type="checkbox" checked={f.endless} onChange={(e) => set('endless', e.target.checked)} />
								Endless belt
							</label>
							{f.endless ? (
								<p className="auth-hint">
									No length limit when slicing: long rows, many copies and big groups of models all fit. The plate is drawn{' '}
									{ENDLESS_BELT_LENGTH_MM} mm long.
								</p>
							) : (
								<label>
									Belt length (Y, mm)
									<input type="number" step="1" value={f.beltLength} onChange={(e) => set('beltLength', e.target.value)} />
								</label>
							)}
						</div>
					)}
				</div>
				<div className="printer-bed-drawing">
					<BedDrawing f={f} />
				</div>
			</div>
		</>
	);
}

// Which process and material the printer starts with.
function DefaultsSection({
	f,
	set,
	processChoices,
	materialChoices,
}: {
	f: Fields;
	set: SetField;
	processChoices: ProfileSummary[];
	materialChoices: ProfileSummary[];
}) {
	return (
		<>
			<h3 className="material-section">When it is picked</h3>
			<div className="material-grid">
				<label>
					Default process
					<select value={f.process} onChange={(e) => set('process', e.target.value)}>
						{f.process && !processChoices.some((p) => p.name === f.process) && <option value={f.process}>{f.process}</option>}
						{processChoices.map((p) => (
							<option key={`${p.vendor}/${p.name}`} value={p.name}>
								{p.name}
							</option>
						))}
					</select>
				</label>
				<label>
					Default material
					<select value={f.material} onChange={(e) => set('material', e.target.value)}>
						{f.material && !materialChoices.some((p) => p.name === f.material) && <option value={f.material}>{f.material}</option>}
						{materialChoices.map((p) => (
							<option key={`${p.vendor}/${p.name}`} value={p.name}>
								{p.name}
							</option>
						))}
					</select>
				</label>
			</div>
		</>
	);
}

// The printer's name, what it starts from, and a line saying what that means.
function StartFromRow({
	mode,
	name,
	onName,
	current,
	baseKey,
	onBase,
	baseNote,
	startOptions,
	baseLabel,
}: {
	mode: 'create' | 'edit';
	name: string;
	onName: (name: string) => void;
	current: { name: string } | null;
	baseKey: string;
	onBase: (key: string) => void;
	baseNote: string;
	startOptions: ReturnType<typeof startOptionsFor>;
	baseLabel: string;
}) {
	return (
		<>
			<div className="material-grid">
				<label>
					Name
					<input type="text" value={name} readOnly={mode === 'edit'} maxLength={120} onChange={(e) => onName(e.target.value)} />
				</label>
				{mode === 'create' ? (
					<label>
						Start from (optional)
						<select value={baseKey} onChange={(e) => onBase(e.target.value)}>
							{current && <option value="selected">{current.name} (selected printer)</option>}
							<option value="nothing">Nothing: start from generic defaults</option>
							{startOptions.generics.length > 0 && (
								<optgroup label="Generic starting points">
									{startOptions.generics.map((p) => (
										<option key={p.name} value={`p:${p.name}`}>
											{p.name}
										</option>
									))}
								</optgroup>
							)}
							{startOptions.mine.length > 0 && (
								<optgroup label="My printers">
									{startOptions.mine.map((p) => (
										<option key={p.name} value={`p:${p.name}`}>
											{p.name}
										</option>
									))}
								</optgroup>
							)}
						</select>
					</label>
				) : (
					<label>
						Based on
						<input type="text" value={baseNote || 'Nothing in particular'} readOnly />
					</label>
				)}
			</div>
			<p className="profile-import-help">
				{mode === 'create' ? (
					<>
						Starts from <strong>{baseLabel}</strong>; anything you leave alone is inherited from it. Saved under{' '}
						<strong>My profiles</strong>.
					</>
				) : (
					<>Settings not shown here, and any you added under Advanced, stay as they are.</>
				)}
			</p>
		</>
	);
}

/**
 * The "New printer" / "Edit printer" form: a copy of a printer (or of the slicer's generic printer for a
 * firmware, or of nothing in particular) with the settings people change on the Basics tab, and every other
 * printer setting reachable by search on the Advanced tab. Saved under "My profiles"; whatever the form does
 * not set is inherited.
 */
export default function PrinterDialog({ mode, current, profiles, schema, onClose, onSaved }: PrinterDialogProps) {
	const [tab, setTab] = useState<Tab>('basics');
	const [name, setName] = useState(initialName(mode, current));
	const [f, setF] = useState<Fields>(EMPTY);
	const touched = useRef(new Set<string>());
	const [baseKey, setBaseKey] = useState<string>(initialBaseKey(mode, current));
	const [inherited, setInherited] = useState<Record<string, unknown>>({});
	const [advanced, setAdvanced] = useState<Record<string, string>>({});
	const [printerKeys, setPrinterKeys] = useState<string[]>([]);
	const [loading, setLoading] = useState(true);
	const [loadError, setLoadError] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [saving, setSaving] = useState(false);
	const [baseNote, setBaseNote] = useState('');

	const defs = useMemo(() => new Map(schema.map((s) => [s.key, s])), [schema]);
	const set = <K extends keyof Fields>(key: K, value: Fields[K]) => {
		touched.current.add(key);
		setF((prev) => ({ ...prev, [key]: value }));
	};

	// Where each choice in "Start from" comes from.
	const startOptions = useMemo(() => startOptionsFor(profiles), [profiles]);

	// The preset a choice of "Start from" means.
	const baseFor = useCallback(
		(key: string, flavour: string, belt: boolean): { vendor: string; name: string } | null => {
			if (key === 'selected' || key === 'edit') return current;
			const wanted = key === 'nothing' ? genericName(flavour, belt) : key.replace(/^p:/, '');
			const found = profiles.find((p) => p.kind === 'machine' && p.name === wanted);
			return found ? { vendor: found.vendor, name: found.name } : null;
		},
		[current, profiles],
	);

	// Load a base and fill the Basics fields the user has not typed in yet.
	const loadBase = useCallback(
		(key: string, flavour: string, belt: boolean, keepTouched: boolean) => {
			const target = baseFor(key, flavour, belt);
			if (!target) {
				setLoading(false);
				return Promise.resolve();
			}
			setLoading(true);
			return getProfileDetail(target.vendor, 'machine', target.name)
				.then((detail) => {
					setInherited(detail.data);
					const next = fieldsFrom(detail.data);
					setF((prev) => mergeFields(prev, next, touched.current, keepTouched));
					setLoadError(null);
				})
				.catch((err: Error) => setLoadError(message(err)))
				.finally(() => setLoading(false));
		},
		[baseFor],
	);

	// Open: fill from the printer (create: the one selected, or generic defaults; edit: the printer itself).
	// biome-ignore lint/correctness/useExhaustiveDependencies: runs once when the dialog opens, from the printer it was opened with
	useEffect(() => {
		let cancelled = false;
		getPrinterKeys()
			.then((keys) => !cancelled && setPrinterKeys(keys))
			.catch(() => undefined);
		if (mode === 'edit' && current) {
			Promise.all([getProfileDetail(current.vendor, 'machine', current.name), getStoredPrinter(current.name), getPrinterKeys()])
				.then(([detail, stored, keys]) => {
					if (cancelled) return;
					setInherited(detail.data);
					setF((prev) => ({ ...prev, ...fieldsFrom(detail.data) }));
					// The settings this printer holds beyond the form's own become its advanced list.
					setAdvanced(extraSettings(stored, keys));
					setBaseNote(typeof stored.inherits === 'string' ? stored.inherits : '');
				})
				.catch((err: Error) => !cancelled && setLoadError(message(err)))
				.finally(() => !cancelled && setLoading(false));
		} else {
			loadBase(baseKey, EMPTY.flavour, false, false).then(() => undefined);
		}
		return () => {
			cancelled = true;
		};
		// Opened once for the printer it was opened on.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);

	const chooseBase = (key: string) => {
		setBaseKey(key);
		void loadBase(key, f.flavour, f.belt, true);
	};
	// With no base, the firmware (and a belt) pick the generic printer to start from.
	const changeFlavour = (flavour: string) => {
		set('flavour', flavour);
		if (baseKey === 'nothing') void loadBase('nothing', flavour, f.belt, true).then(() => setF((prev) => ({ ...prev, flavour })));
	};
	const changeBelt = (belt: boolean) => {
		set('belt', belt);
		if (baseKey === 'nothing') void loadBase('nothing', f.flavour, belt, true).then(() => setF((prev) => ({ ...prev, belt })));
	};

	const flavourDef = defs.get('gcode_flavor');
	const nozzleTypeDef = defs.get('nozzle_type');

	const save = () => {
		const cleanName = name.trim();
		if (!cleanName) {
			setError('Give the printer a name');
			return;
		}
		let form: PrinterForm;
		try {
			const baseName = mode === 'create' ? (baseFor(baseKey, f.flavour, f.belt)?.name ?? null) : undefined;
			form = buildPrinterForm(f, cleanName, baseName, advanced);
		} catch (err) {
			setError((err as Error).message);
			return;
		}
		setSaving(true);
		setError(null);
		(mode === 'create' ? createPrinterProfile(form) : updatePrinterProfile(form))
			.then((saved) => onSaved(saved.name))
			.catch((err: Error) => {
				setError(message(err));
				setSaving(false);
			});
	};

	const processChoices = useMemo(() => profileChoices(profiles, 'process', f.process), [profiles, f.process]);
	const materialChoices = useMemo(() => profileChoices(profiles, 'filament', f.material), [profiles, f.material]);
	const title = mode === 'create' ? 'New printer' : 'Edit printer';
	const baseLabel = (() => {
		const target = baseFor(baseKey, f.flavour, f.belt);
		return target ? target.name : 'the slicer’s generic printer';
	})();

	return (
		<div className="object-picker printer-dialog" role="dialog" aria-modal="true" aria-label={title}>
			<div className="object-picker-header">
				<strong>{title}</strong>
				<button type="button" className="link-button" onClick={onClose}>
					Close ✕
				</button>
			</div>
			<div className="dialog-tabs" role="tablist">
				{(['basics', 'advanced'] as Tab[]).map((t) => (
					<button key={t} type="button" role="tab" aria-selected={tab === t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>
						{t === 'basics' ? 'Basics' : `Advanced${Object.keys(advanced).length ? ` (${Object.keys(advanced).length})` : ''}`}
					</button>
				))}
			</div>
			<div className="object-picker-scroll material-form">
				{loadError && <p className="banner-error">{loadError}</p>}
				{loading && <p className="auth-hint">Loading…</p>}

				{tab === 'basics' && (
					<>
						<StartFromRow
							mode={mode}
							name={name}
							onName={setName}
							current={current}
							baseKey={baseKey}
							onBase={chooseBase}
							baseNote={baseNote}
							startOptions={startOptions}
							baseLabel={baseLabel}
						/>
						<BuildPlateSection f={f} set={set} onBelt={changeBelt} />

						<h3 className="material-section">Nozzle and firmware</h3>
						<div className="material-grid material-grid-4">
							<label>
								Nozzle (mm)
								<input type="number" step="0.05" value={f.nozzle} onChange={(e) => set('nozzle', e.target.value)} />
							</label>
							<label>
								Nozzle type
								<select value={f.nozzleType} onChange={(e) => set('nozzleType', e.target.value)}>
									<option value="">Unchanged</option>
									{(nozzleTypeDef?.enum_values ?? []).map((v) => (
										<option key={v} value={v}>
											{labelFor(nozzleTypeDef, v)}
										</option>
									))}
								</select>
							</label>
							<label>
								G-code flavour
								<select value={f.flavour} onChange={(e) => changeFlavour(e.target.value)}>
									{(flavourDef?.enum_values ?? [f.flavour]).map((v) => (
										<option key={v} value={v}>
											{labelFor(flavourDef, v)}
										</option>
									))}
								</select>
							</label>
							<label className="checkbox-label printer-aux">
								<input type="checkbox" checked={f.auxFan} onChange={(e) => set('auxFan', e.target.checked)} />
								Auxiliary fan
							</label>
						</div>

						<h3 className="material-section">Start and end G-code</h3>
						<div className="material-grid">
							<label>
								Start G-code
								<textarea
									className="gcode-box"
									rows={7}
									value={f.start}
									spellCheck={false}
									onChange={(e) => set('start', e.target.value)}
								/>
							</label>
							<label>
								End G-code
								<textarea className="gcode-box" rows={7} value={f.end} spellCheck={false} onChange={(e) => set('end', e.target.value)} />
							</label>
						</div>
						<p className="auth-hint">Words in [square brackets] are filled in when slicing (temperatures, bed size and so on).</p>

						<h3 className="material-section">Motion and retraction</h3>
						<div className="material-grid material-grid-4">
							<label>
								Max speed (mm/s)
								<input type="number" step="1" value={f.maxSpeed} onChange={(e) => set('maxSpeed', e.target.value)} />
							</label>
							<label>
								Max acceleration (mm/s²)
								<input type="number" step="10" value={f.maxAccel} onChange={(e) => set('maxAccel', e.target.value)} />
							</label>
							<label>
								Retraction (mm)
								<input type="number" step="0.1" value={f.retractLen} onChange={(e) => set('retractLen', e.target.value)} />
							</label>
							<label>
								Retraction speed (mm/s)
								<input type="number" step="1" value={f.retractSpeed} onChange={(e) => set('retractSpeed', e.target.value)} />
							</label>
							<label>
								Z hop (mm)
								<input type="number" step="0.1" value={f.zHop} onChange={(e) => set('zHop', e.target.value)} />
							</label>
						</div>

						<DefaultsSection f={f} set={set} processChoices={processChoices} materialChoices={materialChoices} />
						<p className="auth-hint">
							Anything else: the{' '}
							<button type="button" className="link-button" onClick={() => setTab('advanced')}>
								Advanced
							</button>{' '}
							tab.
						</p>
					</>
				)}

				{tab === 'advanced' && (
					<AdvancedSettingsTab
						keys={printerKeys}
						defs={defs}
						advanced={advanced}
						onChange={setAdvanced}
						inherited={inherited}
						noun="printer"
						placeholder="retract, pause, exclude …"
					/>
				)}

				{error && <p className="banner-error">{error}</p>}
				<div className="material-actions">
					<button type="button" className="preview-button" onClick={onClose}>
						Cancel
					</button>
					<button type="button" onClick={save} disabled={loading || saving}>
						{saving ? 'Saving…' : 'Save printer'}
					</button>
				</div>
			</div>
		</div>
	);
}
