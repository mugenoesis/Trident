import type { ResinChoice, ResinInfo, ResinPrinterInfo } from './types';

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

export function formatMl(ml: number): string {
	return `${ml.toFixed(1)} ml`;
}

// "Using Siraya Tech's published settings for 0.05 mm layers. ..." -- what a resin's row is for.
export function choiceNote(choice: ResinChoice, vendor: string, printer: ResinPrinterInfo): string {
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

// A saved resin printer keeps the slice settings as {process, values}; what was saved by an older or newer version is read as far as it fits.
export function packResinSettings(process: ResinProcess, values: ResinValues): Record<string, unknown> {
	return { process, values };
}

export function unpackResinSettings(saved: Record<string, unknown>): { process: ResinProcess; values: ResinValues | null } {
	const process = { ...DEFAULT_RESIN_PROCESS, ...(typeof saved.process === 'object' && saved.process ? saved.process : {}) };
	const values = typeof saved.values === 'object' && saved.values ? { ...EMPTY_RESIN_VALUES, ...saved.values } : null;
	return { process, values };
}
