import type { MyResinPrinterRequest, ResinChoice, ResinFormat, ResinInfo, ResinPrinterInfo } from './types';

// The vendor the user's own resins are listed under (the API puts them there).
export const MY_RESINS = 'My resins';

export const RESIN_LAYER_HEIGHTS = ['0.025', '0.03', '0.05', '0.1'];

export type SupportLevel = 'none' | 'light' | 'medium' | 'heavy';
export type PadMode = 'off' | 'under' | 'model';

export const SUPPORT_LEVELS: { value: SupportLevel; label: string }[] = [
	{ value: 'none', label: 'None' },
	{ value: 'light', label: 'Light' },
	{ value: 'medium', label: 'Medium' },
	{ value: 'heavy', label: 'Heavy' },
];

export const PAD_MODES: { value: PadMode; label: string }[] = [
	{ value: 'off', label: 'Off: model sits on supports' },
	{ value: 'under', label: 'Pad under the supports' },
	{ value: 'model', label: 'Model sits on the pad' },
];

// How many support points the slicer puts per area, relative to its own default of 100.
const SUPPORT_DENSITY: Record<Exclude<SupportLevel, 'none'>, number> = {
	light: 70,
	medium: 100,
	heavy: 150,
};

// The resin's own values the screen shows, and the setting each one is.
export const RESIN_VALUE_FIELDS = [
	{ key: 'exposure_time', label: 'Exposure', unit: 's' },
	{ key: 'initial_exposure_time', label: 'Bottom exposure', unit: 's' },
	{ key: 'bottom_layer_count', label: 'Bottom layers', unit: '' },
	{ key: 'faded_layers', label: 'Transition layers', unit: '' },
	{ key: 'lift_distance', label: 'Lift distance', unit: 'mm' },
	{ key: 'lift_speed', label: 'Lift speed', unit: 'mm/min' },
	// What a bottle cost and holds: with the resin used, the cost of a print. Left empty, no cost is shown.
	{ key: 'bottle_cost', label: 'Bottle price', unit: '' },
	{ key: 'bottle_volume', label: 'Bottle size', unit: 'ml' },
] as const;

type ResinValueKey = (typeof RESIN_VALUE_FIELDS)[number]['key'];
export type ResinValues = Record<ResinValueKey, string>;

export interface ResinProcess {
	layerHeight: string;
	supports: SupportLevel;
	touchpoint: string;
	pad: PadMode;
	hollow: boolean;
	wallThickness: string;
}

export const DEFAULT_RESIN_PROCESS: ResinProcess = {
	layerHeight: '0.05',
	supports: 'medium',
	touchpoint: '0.4',
	pad: 'off',
	hollow: true,
	wallThickness: '2',
};

export const EMPTY_RESIN_VALUES: ResinValues = {
	exposure_time: '',
	initial_exposure_time: '',
	bottom_layer_count: '',
	faded_layers: '',
	lift_distance: '',
	lift_speed: '',
	bottle_cost: '',
	bottle_volume: '',
};

// The text of a resin's values as the inputs show them.
export function valuesFromChoice(choice: ResinChoice): ResinValues {
	const values = { ...EMPTY_RESIN_VALUES };
	for (const { key } of RESIN_VALUE_FIELDS) {
		const v = choice.settings[key];
		if (v !== undefined) values[key] = String(v);
	}
	return values;
}

function numberOrNull(text: string): number | null {
	const n = Number(text);
	return text.trim() !== '' && Number.isFinite(n) ? n : null;
}

// The resin values on screen that have a number in them, by setting.
export function numericValues(values: ResinValues): Record<string, number> {
	const out: Record<string, number> = {};
	for (const { key } of RESIN_VALUE_FIELDS) {
		const n = numberOrNull(values[key]);
		if (n !== null) out[key] = n;
	}
	return out;
}

// What the slicer is told besides the resin's own file: the process, and every value the screen shows that has a number in it.
export function resinOverrides(process: ResinProcess, values: ResinValues): Record<string, unknown> {
	const overrides: Record<string, unknown> = {
		layer_height: Number(process.layerHeight),
		supports_enable: process.supports !== 'none',
		pad_enable: process.pad !== 'off',
		hollowing_enable: process.hollow,
	};
	if (process.supports !== 'none') {
		overrides.support_points_density_relative = SUPPORT_DENSITY[process.supports];
		const head = numberOrNull(process.touchpoint);
		if (head !== null) overrides.support_head_front_diameter = head;
	}
	if (process.pad !== 'off') overrides.pad_zero_elevation = process.pad === 'model';
	const wall = numberOrNull(process.wallThickness);
	if (process.hollow && wall !== null) overrides.hollowing_min_thickness = wall;
	return { ...overrides, ...numericValues(values) };
}

export function resinDisplayName(resin: ResinInfo): string {
	return resin.name.startsWith(`${resin.vendor} `) ? resin.name.slice(resin.vendor.length + 1) : resin.name;
}

export function uniqueVendors(items: { vendor: string }[]): string[] {
	return [...new Set(items.map((i) => i.vendor))].sort((a, b) => a.localeCompare(b));
}

export function formatDuration(seconds: number): string {
	const minutes = Math.max(1, Math.round(seconds / 60));
	const h = Math.floor(minutes / 60);
	return h > 0 ? `${h} h ${minutes % 60} min` : `${minutes} min`;
}

// The cost of the resin a job used at the bottle price and size it was sliced with, or null when it was not given both.
export function resinCost(usedMl: number | null, overrides: Record<string, unknown>): number | null {
	const price = Number(overrides.bottle_cost);
	const size = Number(overrides.bottle_volume);
	if (usedMl === null || !(price > 0) || !(size > 0)) return null;
	return (usedMl * price) / size;
}

export function formatCost(cost: number): string {
	return cost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function formatMl(ml: number): string {
	return `${ml.toFixed(1)} ml`;
}

// "Using Siraya Tech's published settings for 0.05 mm layers. ..." -- what a resin's row is for.
// What a resin with no settings for the printer offers: the resin's own values carried over, and the other printer's numbers as a reference.
function startingPointNote(choice: ResinChoice, vendor: string, printer: ResinPrinterInfo): string {
	const ref = choice.reference_settings;
	const numbers =
		ref.exposure_time !== undefined && ref.initial_exposure_time !== undefined
			? ` (${choice.reference_printer} used ${ref.exposure_time} s and ${ref.initial_exposure_time} s)`
			: '';
	return `No settings for the ${printer.model} yet. Starting from ${choice.reference_printer}'s values for this ${vendor} resin at ${choice.layer_height} mm: the bottom and transition layers are carried over. Exposure depends on your printer's light, so it is yours to fill in${numbers}. Test it, then make your own resin based on this config to keep it for the ${printer.model}.`;
}

// What an empty value box hints at for a starting point: the other printer's number, or that the printer's own default is used.
export function startingPointHint(choice: ResinChoice | null, key: string, unit: string): string | undefined {
	if (choice?.match !== 'other') return undefined;
	const value = choice.reference_settings[key];
	if (key === 'exposure_time' || key === 'initial_exposure_time')
		return value === undefined ? undefined : `${value} ${unit} on ${choice.reference_printer}`;
	if (key === 'lift_distance' || key === 'lift_speed') return "printer's own";
	return undefined;
}

export function choiceNote(choice: ResinChoice, vendor: string, printer: ResinPrinterInfo): string {
	if (choice.match === 'other') return startingPointNote(choice, vendor, printer);
	if (vendor === MY_RESINS) return `Using your own values for ${choice.layer_height} mm layers.`;
	const layers = `${choice.layer_height} mm layers`;
	const layerPart = choice.exact_layer_height ? `for ${layers}` : `for ${layers} (the nearest to the layer height chosen)`;
	const printerPart =
		choice.match === 'exact'
			? ''
			: choice.match === 'vendor'
				? ` They have no row for the ${printer.model}, so the row for another ${printer.vendor} printer is used.`
				: ` They have no row for the ${printer.model}, so their general row is used.`;
	return `Using ${vendor}'s published settings ${layerPart}.${printerPart}`;
}

// The bottle price and size are about the bottle in the user's hand, not the printer or layer height: they stay when the resin's own values are
// reloaded for another layer height (unless the resin itself says what a bottle holds and costs).
export function keepBottle(next: ResinValues, previous: ResinValues, choice: ResinChoice): ResinValues {
	const kept = { ...next };
	for (const key of ['bottle_cost', 'bottle_volume'] as const) {
		if (choice.settings[key] === undefined) kept[key] = previous[key];
	}
	return kept;
}

// A saved resin printer keeps the slice settings as {process, values}; what was saved by an older or newer version is read as far as it fits.
export function packResinSettings(process: ResinProcess, values: ResinValues): Record<string, unknown> {
	return { process, values };
}

export function unpackResinSettings(saved: Record<string, unknown>): { process: ResinProcess; values: ResinValues | null } {
	const process = { ...DEFAULT_RESIN_PROCESS, ...(typeof saved.process === 'object' && saved.process ? saved.process : {}) };
	const values = typeof saved.values === 'object' && saved.values ? { ...EMPTY_RESIN_VALUES, ...saved.values } : null;
	return { process, values };
}

// The vendor the user's own printers are listed under (the API puts them there).
export const MY_PRINTERS = 'My printers';

// The pixel size in mm of a screen of this width and height and these pixel counts, or null while a number is missing.
function pixelPitch(form: MyResinPrinterRequest): { x: number; y: number } | null {
	const { display_width_mm: w, display_height_mm: h, pixels_x: px, pixels_y: py } = form;
	return w > 0 && h > 0 && px > 0 && py > 0 ? { x: w / px, y: h / py } : null;
}

// What is wrong with the numbers of a printer, in the words of the server's check (a printer rejects a file that does not match its
// screen, and says nothing about why), or null when they fit; also the pixel size to show when they do.
export function checkPrinterNumbers(form: MyResinPrinterRequest): { problem: string | null; pitch: { x: number; y: number } | null } {
	const pitch = pixelPitch(form);
	if (!pitch) return { problem: null, pitch };
	const size = `${pitch.x.toFixed(4)} × ${pitch.y.toFixed(4)} mm`;
	if (Math.min(pitch.x, pitch.y) < 0.005 || Math.max(pitch.x, pitch.y) > 0.5) {
		return { problem: `These numbers give pixels of ${size}, which no resin screen has: check them.`, pitch };
	}
	if (!form.rectangular_pixels && Math.abs(pitch.x / pitch.y - 1) > 0.02) {
		return {
			problem: `These numbers give pixels of ${size}, which are not square: check the screen size and the pixel counts (a printer rejects a file that does not match its screen), or say the pixels are rectangular.`,
			pitch,
		};
	}
	return { problem: null, pitch };
}

// The form for a printer of your own, started from a printer of the catalogue (or from nothing).
export function formFromPrinter(printer: ResinPrinterInfo | null, formats: ResinFormat[]): MyResinPrinterRequest {
	const writable = printer && formats.some((f) => f.id === printer.format);
	return {
		name: '',
		display_width_mm: printer?.display_width_mm ?? 0,
		display_height_mm: printer?.display_height_mm ?? 0,
		pixels_x: printer?.pixels_x ?? 0,
		pixels_y: printer?.pixels_y ?? 0,
		build_height_mm: printer?.build_height_mm ?? 0,
		format: writable ? printer.format : (formats[0]?.id ?? ''),
		copy_from: printer && printer.vendor !== MY_PRINTERS ? printer.name : null,
		mirror_x: printer?.mirror_x ?? false,
		mirror_y: printer?.mirror_y ?? false,
		rectangular_pixels: printer?.nonsquare_pixels ?? false,
	};
}
