import type { FilamentSlot } from './appHelpers';
import type { RowMode } from './beltLayout';
import type { QuickSettingsValues } from './components/QuickSettings';
import type { Placement } from './types';

// What the quick settings and the advanced list say to the slicer, as setting overrides.
export function quickOverrides(quickSettings: QuickSettingsValues, advancedOverrides: Record<string, string>): Record<string, string> {
	const overrides: Record<string, string> = {
		...advancedOverrides,
		layer_height: quickSettings.layer_height,
		sparse_infill_density: `${quickSettings.sparse_infill_density}%`,
		wall_loops: quickSettings.wall_loops,
		sparse_infill_pattern: quickSettings.sparse_infill_pattern,
		curr_bed_type: quickSettings.curr_bed_type,
		enable_support: quickSettings.enable_support,
		enable_prime_tower: quickSettings.enable_prime_tower,
	};
	// Empty means "use the process profile's own value" -- see QuickSettings.
	if (quickSettings.seam_position) overrides.seam_position = quickSettings.seam_position;
	if (quickSettings.brim_type) overrides.brim_type = quickSettings.brim_type;
	// Only meaningful (and only worth sending) when support is actually on.
	if (quickSettings.enable_support === '1') {
		overrides.support_type = quickSettings.support_type;
		// NOTE: the real FDM option is "support_on_build_plate_only" --
		// "support_buildplate_only" is a same-named-looking but unrelated SLA
		// option (SLAPrintObjectConfig, PrintConfig.cpp) that silently no-ops
		// for every FDM print. Confirmed via direct API test: overriding the
		// wrong key left filament_used_g unchanged, while the correct key
		// changed it (19.52g -> 17.24g on a support-enabled Benchy).
		overrides.support_on_build_plate_only = quickSettings.support_buildplate_only;
	}
	return overrides;
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

// One nozzle per head, each with its own diameter and type.
function multiHeadNozzles(filamentSlots: FilamentSlot[], advancedOverrides: Record<string, string>): Record<string, string> {
	const overrides: Record<string, string> = {};
	const diameters = filamentSlots.map((s) => s.nozzleDiameter);
	if (diameters.every((d) => Number.isFinite(d) && d > 0)) {
		overrides.nozzle_diameter = diameters.join(',');
		// Confirmed via direct CLI testing: a mixed-diameter toolchanger's
		// own bundled process profile can fail slicing outright ("Bridge
		// line width must not exceed nozzle diameter") because its default
		// bridge_line_width was sized for its smaller nozzle but validated
		// against its largest -- clamp to the smallest configured nozzle
		// whenever there's genuine diameter variation, unless the user has
		// already set this explicitly via Advanced settings.
		if (new Set(diameters).size > 1 && !('bridge_line_width' in advancedOverrides)) {
			overrides.bridge_line_width = String(Math.min(...diameters));
		}
	}
	if (filamentSlots.some((s) => s.nozzleType && s.nozzleType !== 'undefine')) {
		overrides.nozzle_type = filamentSlots.map((s) => s.nozzleType || 'undefine').join(',');
	}
	return overrides;
}

// One physical hotend feeding every slot, so a single value applies to all of them.
function sharedNozzle(slotCount: number, globalNozzleDiameter: string, globalNozzleType: string): Record<string, string> {
	const overrides: Record<string, string> = {};
	const dia = Number(globalNozzleDiameter);
	if (globalNozzleDiameter.trim() !== '' && Number.isFinite(dia) && dia > 0) {
		overrides.nozzle_diameter = Array(slotCount || 1)
			.fill(dia)
			.join(',');
	}
	if (globalNozzleType && globalNozzleType !== 'undefine') {
		overrides.nozzle_type = Array(slotCount || 1)
			.fill(globalNozzleType)
			.join(',');
	}
	return overrides;
}

// The nozzle diameter and type the slicer is told about.
export function nozzleOverrides(
	isMultiHeadPrinter: boolean,
	filamentSlots: FilamentSlot[],
	advancedOverrides: Record<string, string>,
	globalNozzleDiameter: string,
	globalNozzleType: string,
): Record<string, string> {
	return isMultiHeadPrinter
		? multiHeadNozzles(filamentSlots, advancedOverrides)
		: sharedNozzle(filamentSlots.length, globalNozzleDiameter, globalNozzleType);
}

// "old:new" pairs for every file role that is printed with a different extruder than the file gave it.
export function remapPairsOf(roleNozzleAssignments: (number | null)[]): string[] {
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
	const remapPairs: string[] = [];
	roleNozzleAssignments.forEach((slotIdx, roleIdx) => {
		if (slotIdx === null) return;
		const oldExtruder = roleIdx + 1;
		const newExtruder = slotIdx + 1;
		if (oldExtruder !== newExtruder) remapPairs.push(`${oldExtruder}:${newExtruder}`);
	});
	return remapPairs;
}

interface JobInputs {
	modelId: string;
	printerName: string;
	processName: string;
	previewImageBase64: string | undefined;
	filamentProfiles: string[];
	overrides: Record<string, string>;
	plateIndex: number | null;
	placement: Placement | null;
	copies: number;
	excludedObjects: number[] | undefined;
	beltLayout: { order: number[]; gap_mm: number; mode: RowMode } | undefined;
}

// The request that starts a slicing job.
export function jobRequestOf(i: JobInputs) {
	return {
		model_id: i.modelId,
		printer_profile: i.printerName,
		process_profile: i.processName,
		preview_image_base64: i.previewImageBase64,
		filament_profiles: i.filamentProfiles,
		setting_overrides: i.overrides,
		plate_index: i.plateIndex ?? undefined,
		placement: i.placement ?? undefined,
		copies: i.copies > 1 ? i.copies : undefined,
		excluded_objects: i.excludedObjects,
		belt_layout: i.beltLayout,
	};
}
