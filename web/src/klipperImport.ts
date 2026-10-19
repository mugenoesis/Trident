import type { Fields } from './components/PrinterDialog';
import type { KlipperImportResult, PrinterForm } from './types';

// What reading a Klipper printer gives, in the terms of the New printer dialog: the Basics fields it fills, the tag each filled
// field carries, and the lines that say what was read and where.

type TextField =
	| 'width'
	| 'depth'
	| 'height'
	| 'originX'
	| 'originY'
	| 'nozzle'
	| 'maxSpeed'
	| 'maxAccel'
	| 'retractLen'
	| 'retractSpeed'
	| 'start'
	| 'end';

// The form's number or text fields and the dialog's (text) field each fills.
const TEXT_FIELDS: [keyof PrinterForm, TextField][] = [
	['width', 'width'],
	['depth', 'depth'],
	['height', 'height'],
	['origin_x', 'originX'],
	['origin_y', 'originY'],
	['nozzle_diameter', 'nozzle'],
	['max_speed', 'maxSpeed'],
	['max_acceleration', 'maxAccel'],
	['retraction_length', 'retractLen'],
	['retraction_speed', 'retractSpeed'],
	['start_gcode', 'start'],
	['end_gcode', 'end'],
];

// The dialog field a finding is for (the same names as the form's, apart from these).
const FIELD_OF_FINDING: Record<string, keyof Fields> = {
	shape: 'shape',
	origin_centre: 'originCentre',
	nozzle_diameter: 'nozzle',
	origin_x: 'originX',
	origin_y: 'originY',
	max_speed: 'maxSpeed',
	max_acceleration: 'maxAccel',
	retraction_length: 'retractLen',
	retraction_speed: 'retractSpeed',
	start_gcode: 'start',
	end_gcode: 'end',
	width: 'width',
	depth: 'depth',
	height: 'height',
};

/** The Basics fields a printer read from Klipper fills (a value the server left out, or sent as null, is left alone). */
export function fieldsFromKlipper(form: PrinterForm): Partial<Fields> {
	const out: Partial<Fields> = {};
	if (form.gcode_flavor) out.flavour = form.gcode_flavor;
	if (form.shape) out.shape = form.shape;
	if (form.origin_centre != null) out.originCentre = form.origin_centre;
	for (const [key, field] of TEXT_FIELDS) {
		const value = form[key];
		if (typeof value === 'number' || typeof value === 'string') out[field] = String(value);
	}
	return out;
}

interface FieldTag {
	// ok: read from the printer; check: read, but worth a second look.
	kind: 'ok' | 'check';
	// What the field held when it was read: the tag goes once the user types something else.
	value: string;
}

export type FieldTags = Partial<Record<keyof Fields, FieldTag>>;

/** The tag each filled field of the dialog carries, by field. */
export function tagsFromKlipper(result: KlipperImportResult): FieldTags {
	const tags: FieldTags = {};
	for (const finding of result.findings) {
		const field = FIELD_OF_FINDING[finding.field];
		if (field) tags[field] = { kind: finding.check ? 'check' : 'ok', value: String(finding.value) };
	}
	return tags;
}

// What each finding is called in "Where each value was read".
const LABELS: Record<string, string> = {
	shape: 'Bed shape',
	width: 'Width',
	depth: 'Depth',
	height: 'Max height',
	origin_x: 'Origin X offset',
	origin_y: 'Origin Y offset',
	origin_centre: 'Origin at the centre',
	nozzle_diameter: 'Nozzle',
	max_speed: 'Max speed',
	max_acceleration: 'Max acceleration',
	retraction_length: 'Retraction',
	retraction_speed: 'Retraction speed',
	start_gcode: 'Start G-code',
	end_gcode: 'End G-code',
	'advanced.use_firmware_retraction': 'Firmware retraction',
};

export interface SourceRow {
	label: string;
	value: string;
	source: string;
}

// A switch the slicer keeps as "1" (or a yes/no the form keeps as true) reads as words.
const shown = (value: string | number | boolean): string => (value === '1' ? 'on' : value === true ? 'yes' : String(value));

/** The lines of "Where each value was read": what, its value, and where it came from. */
export function sourceRows(result: KlipperImportResult): SourceRow[] {
	return result.findings.map((f) => ({
		label: LABELS[f.field] ?? f.field,
		value: shown(f.value),
		source: f.source,
	}));
}

// The groups the green line names, by the findings that belong to each.
const GROUPS: [string, string[]][] = [
	['the build plate', ['shape', 'width', 'depth', 'height', 'origin_x', 'origin_y', 'origin_centre']],
	['nozzle', ['nozzle_diameter']],
	['speeds', ['max_speed', 'max_acceleration']],
	['retraction', ['retraction_length', 'retraction_speed', 'advanced.use_firmware_retraction']],
	['the start G-code', ['start_gcode']],
	['the end G-code', ['end_gcode']],
];

/** "the build plate, nozzle, speeds and the end G-code": what was filled in. */
export function filledIn(result: KlipperImportResult): string {
	const fields = new Set(result.findings.map((f) => f.field));
	const names = GROUPS.filter(([, keys]) => keys.some((k) => fields.has(k))).map(([name]) => name);
	if (names.length < 2) return names.join('');
	return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}
