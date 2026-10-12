import type { QuickSettingsValues } from './components/QuickSettings';
import type { JobRecord, ProfileSummary, ThreeMfInspection } from './types';

export const ACTIVE_STATUSES: JobRecord['status'][] = ['queued', 'running'];
export const POLL_INTERVAL_MS = 1500;

// A stable fingerprint of everything that actually affects slice output.
// Used to tell "you changed something" apart from "you clicked Slice again
// with the same settings" -- object key order isn't guaranteed to stay
// consistent across state updates, so each object's entries are sorted by
// key before stringifying rather than relying on JSON.stringify's
// insertion-order behavior.
function sortedEntries(obj: Record<string, unknown>): [string, unknown][] {
	return Object.keys(obj)
		.sort()
		.map((key) => [key, obj[key]]);
}

// api/app/gcode_stats.py adds this to a succeeded job's own result blob
// (OrcaSlicer's own result.json never carries it) -- null for any other
// status, or a job whose gcode footer didn't have a parseable line.
export function filamentGramsOf(job: JobRecord | null): number | null {
	if (job?.status !== 'succeeded') return null;
	const grams = job.result?.filament_used_g;
	return typeof grams === 'number' ? grams : null;
}

export function computeSliceSignature(
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
	});
}

export interface FilamentSlot {
	profile: string;
	color: string;
	// OrcaSlicer models both as per-extruder-variant settings (confirmed:
	// vendor/orcaslicer/src/libslic3r/PrintConfig.cpp defines nozzle_type as
	// an array indexed by extruder, same as nozzle_diameter). Only exposed
	// per-slot in the UI for a genuine multi-head printer -- a single-nozzle
	// printer (AMS-style) uses one shared globalNozzleDiameter/globalNozzleType
	// instead, since every slot feeds the same physical hotend.
	nozzleDiameter: number;
	nozzleType: string;
}

// A printer's multi-material/AMS capability can go well past what any one
// bundled catalog profile happens to define -- the user explicitly wants to
// start from whatever printer/process profile fits their machine's process
// settings and manually dial in however many physical heads/AMS slots they
// actually have, rather than being limited to (or having to work around a
// mismatch with) a specific catalog SKU's assumed head count.
export const MAX_FILAMENT_SLOTS = 16;

const NOZZLE_TYPE_LABELS: Record<string, string> = {
	undefine: 'Unspecified',
	hardened_steel: 'Hardened steel',
	stainless_steel: 'Stainless steel',
	tungsten_carbide: 'Tungsten carbide',
	brass: 'Brass',
};
export const FALLBACK_NOZZLE_TYPES = Object.keys(NOZZLE_TYPE_LABELS);

export function nozzleTypeLabel(value: string): string {
	return NOZZLE_TYPE_LABELS[value] ?? value;
}

// Cycled by index when a fresh slot is added (picking a printer with more
// heads/AMS slots than the previous one, or a brand-new upload) so slots
// aren't all identically colored -- purely a UI label, never sent to
// OrcaSlicer.
// Matches entries in COLOR_PRESETS below exactly (not just visually similar
// hex values) so a freshly-added slot's default color always has a
// friendly name available in the nozzle-assignment dropdown, rather than
// falling back to a raw hex code there.
const DEFAULT_SLOT_COLORS = ['#ffffff', '#e0301e', '#0a84ff', '#ffd60a', '#34c759', '#af52de'];

export function defaultSlotColor(index: number): string {
	return DEFAULT_SLOT_COLORS[index % DEFAULT_SLOT_COLORS.length];
}

// One-click presets covering the filament colors people actually load
// (black/white/gray included -- notably absent from DEFAULT_SLOT_COLORS
// above, which only needs to be *distinct* per slot, not comprehensive).
// The native <input type="color"> below still covers anything else. Named
// (not just hex) so a plain-text context that can't render a swatch --
// e.g. a <select><option> in the nozzle-assignment dropdown, which has no
// way to show a colored box -- can still say "Red" instead of "#e0301e".
export const COLOR_PRESETS = [
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
];

const COLOR_NAME_BY_HEX = new Map(COLOR_PRESETS.map(({ hex, name }) => [hex.toLowerCase(), name]));

// Falls back to the raw hex for a custom color picked via the native
// dialog rather than one of the presets above -- still better than no
// label at all when matching a slot to a file's saved color/name.
export function colorLabel(hex: string): string {
	return COLOR_NAME_BY_HEX.get(hex.toLowerCase()) ?? hex;
}

// One slot per physical extruder/AMS slot -- the user controls the count
// directly (starts at 1, "+"/"-" in the Material section; see
// addFilamentSlot/removeFilamentSlot below) rather than it being derived
// from the selected machine profile. nozzleDiameters/nozzleTypes (the
// catalog's own per-extruder-variant values, when known) just seed sensible
// defaults for freshly-built slots -- the user can edit any of it per slot.
export function buildFilamentSlots(
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
	}));
}

// Confirmed via direct CLI testing against a real toolchanger printer
// (Snapmaker U1 0.4+0.6 nozzle): its own bundled process profile's default
// bridge_line_width exceeds 0.6mm-nozzle validation ("Bridge line width
// must not exceed nozzle diameter: 0.600000"), failing *every* slice
// against that machine regardless of which physical nozzle is actually
// used -- a pre-existing bug in the catalog's own data, not anything to
// do with which materials/nozzle a job picks. Clamping to the smallest
// configured nozzle whenever a machine mixes diameters sidesteps it.
export function parsedNozzleDiameters(data: Record<string, unknown> | undefined): number[] {
	const raw = data?.nozzle_diameter;
	if (!Array.isArray(raw)) return [];
	return raw.map((v) => Number(v)).filter((n) => Number.isFinite(n) && n > 0);
}

// A catalog leaf sometimes writes this as a single string rather than an
// array when every nozzle is the same type (confirmed: Snapmaker U1's own
// leaf profiles do this, unlike their nozzle_diameter, which is always a
// real per-slot array) -- broadcast a bare string as a one-element array so
// buildFilamentSlots' "repeat the last value" fallback still seeds every
// slot with it correctly.
export function parsedNozzleTypes(data: Record<string, unknown> | undefined): string[] {
	const raw = data?.nozzle_type;
	if (Array.isArray(raw)) return raw.map((v) => String(v));
	if (typeof raw === 'string' && raw) return [raw];
	return [];
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
export interface FileRole {
	color: string | null;
	name: string | null;
}

export function fileRolesFromInspection(info: ThreeMfInspection | null): FileRole[] {
	if (info?.embedded_filament_colors.length) {
		return info.embedded_filament_colors.map((c, i) => ({
			color: c || null,
			name: info.embedded_filament_names[i] || null,
		}));
	}
	const count = info?.extruder_indices.length || 1;
	return Array.from({ length: count }, () => ({ color: null, name: null }));
}

// Where your own (imported or created) profiles live (api/app/userprofiles.py).
export const IMPORTED_VENDOR = 'My profiles';

// A preset's default process or material comes as a string or a list of them; else the fallback names one.
export function profileNameFrom(raw: unknown, fallback: () => string): string {
	if (typeof raw === 'string') return raw;
	if (Array.isArray(raw) && typeof raw[0] === 'string') return raw[0];
	return fallback();
}

// Not every vendor's machine profile sets these (confirmed empirically:
// BBL does, Afinia doesn't) -- fall back to a profile of that kind for
// the vendor so picking a printer always leaves a slice-able selection
// rather than silently requiring a manual pick. Prefer one actually
// named for this printer (the "0.10mm Standard @BBL A1 0.2 nozzle"
// convention) over just the alphabetically-first one for the vendor.
export function firstOfKind(profiles: ProfileSummary[], vendor: string, printer: string, kind: 'process' | 'filament'): string {
	const inVendor = profiles.filter((p) => p.vendor === vendor && p.kind === kind);
	const namedForPrinter = inVendor.find((p) => p.name.includes(printer));
	if (namedForPrinter) return namedForPrinter.name;
	if (inVendor[0]) return inVendor[0].name;
	return kind === 'filament' ? systemFilamentName(profiles) : '';
}

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
function systemFilamentName(profiles: ProfileSummary[]): string {
	const systemFilaments = profiles.filter((p) => p.kind === 'filament' && p.vendor === 'OrcaFilamentLibrary');
	const genericPla =
		systemFilaments.find((p) => p.name === 'Generic PLA @System') ?? systemFilaments.find((p) => p.name.startsWith('Generic PLA'));
	const chosen = genericPla ?? systemFilaments[0] ?? profiles.find((p) => p.kind === 'filament');
	return chosen?.name ?? '';
}
