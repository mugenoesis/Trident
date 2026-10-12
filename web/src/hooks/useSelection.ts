import type { AppState, MainAppProps } from './useAppState';

export function useSelection(c: AppState & Pick<MainAppProps, never>) {
	const { printers, selectedPrinterId, materials, selectedMaterialId, settingsProfiles, selectedSettingsProfileId, nozzleDiameters } = c;

	const selectedPrinter = printers.find((p) => p.id === selectedPrinterId) ?? null;
	const selectedMaterial = materials.find((m) => m.id === selectedMaterialId) ?? null;
	const selectedSettingsProfile = settingsProfiles.find((p) => p.id === selectedSettingsProfileId) ?? null;

	// Whether this machine has multiple independent physical nozzles/heads,
	// each of which can carry a different size/type (a genuine toolchanger,
	// e.g. Snapmaker U1) vs. one shared nozzle feeding every material slot
	// (AMS-style, e.g. Bambu X1C) -- derived from nozzle_diameter's own array
	// length, the one per-extruder-variant field every catalog machine leaf
	// profile reliably sets directly. Deliberately NOT derived from
	// single_extruder_multi_material: that field is typically only set on a
	// shared ancestor template (confirmed: neither Snapmaker U1 variant nor
	// most Bambu machines set it on their own leaf file), and this backend
	// never flattens `inherits` chains (see api/app/profiles.py) -- so it's
	// absent from detail.data for almost every real machine, which would
	// silently default every printer to "single nozzle" and break the exact
	// multi-head case this control exists for.
	const isMultiHeadPrinter = nozzleDiameters.length > 1;
	return { selectedPrinter, selectedMaterial, selectedSettingsProfile, isMultiHeadPrinter };
}
