import { useCallback } from 'react';
import { getProfileDetail } from '../api';
import { buildFilamentSlots, defaultSlotColor, parsedNozzleDiameters, parsedNozzleTypes } from '../appHelpers';
import { parseBedSize } from '../dimensions';
import type { PrinterRecord } from '../types';
import type { AppState, MainAppProps } from './useAppState';

export function useSavedPrinterApply(c: AppState & Pick<MainAppProps, never>) {
	const {
		setSelectedPrinterId,
		setVendor,
		setPrinterName,
		setProcessName,
		setFilamentSlots,
		setBedSize,
		setScaleToastDismissed,
		setViewMode,
		setNozzleDiameters,
		setNozzleTypes,
		setGlobalNozzleDiameter,
		setGlobalNozzleType,
	} = c;

	// Restores a saved printer's vendor/printer/process/filament/bed-size
	// synchronously (App.tsx already has every piece of state a saved
	// printer snapshots), no network round-trip needed unlike picking a
	// printer fresh via PrinterSelect (handlePrinterChange, above).
	const applySavedPrinter = useCallback(
		(printer: PrinterRecord) => {
			setSelectedPrinterId(printer.id);
			setVendor(printer.vendor);
			setPrinterName(printer.machine_profile);
			setProcessName(printer.process_profile);
			setFilamentSlots(
				printer.filament_profiles.length > 0
					? printer.filament_profiles.map((profile, i) => ({
							profile,
							color: printer.filament_colors[i] ?? defaultSlotColor(i),
							nozzleDiameter: 0.4,
							nozzleType: 'undefine',
						}))
					: buildFilamentSlots(1, ''),
			);
			setBedSize(
				printer.bed_width != null && printer.bed_depth != null && printer.bed_height != null
					? {
							width: printer.bed_width,
							depth: printer.bed_depth,
							height: printer.bed_height,
							// Also backfilled with the machine profile below.
							minX: 0,
							minY: 0,
							// Backfilled a moment later once the machine profile itself
							// loads below (a saved printer record doesn't snapshot these) --
							// false/null here just means the belt-specific placement in
							// Viewer and the GcodeViewer back-transform briefly fall back to
							// their non-belt defaults until then.
							beltPrinterInfiniteY: false,
							beltTransform: null,
						}
					: null,
			);
			setScaleToastDismissed(false);
			setViewMode('model');
			setNozzleDiameters([]);
			setNozzleTypes([]);
			setGlobalNozzleDiameter('');
			setGlobalNozzleType('undefine');
			// The pieces a saved printer record doesn't snapshot itself: the
			// machine profile's actual nozzle_diameter/nozzle_type values (only
			// needed at slice time) -- fetched fresh rather than blocking the
			// otherwise-synchronous restore above on it, then backfilled onto the
			// just-restored slots.
			getProfileDetail(printer.vendor, 'machine', printer.machine_profile)
				.then((detail) => {
					const diameters = parsedNozzleDiameters(detail.data);
					const types = parsedNozzleTypes(detail.data);
					setNozzleDiameters(diameters);
					setNozzleTypes(types);
					setGlobalNozzleDiameter(diameters[0] != null ? String(diameters[0]) : '');
					setGlobalNozzleType(types[0] ?? 'undefine');
					setFilamentSlots((prev) =>
						prev.map((slot, i) => ({
							...slot,
							nozzleDiameter: diameters[i] ?? diameters[diameters.length - 1] ?? slot.nozzleDiameter,
							nozzleType: types[i] ?? types[types.length - 1] ?? slot.nozzleType,
						})),
					);
					// Re-derive from the actual profile now that it's loaded, so a
					// belt printer's beltPrinterInfiniteY flag (not part of the saved
					// printer record itself) reaches the Viewer too.
					const parsedBed = parseBedSize(detail.data);
					if (parsedBed) setBedSize(parsedBed);
				})
				.catch(() => {
					setNozzleDiameters([]);
					setNozzleTypes([]);
				});
		},
		[
			setBedSize,
			setGlobalNozzleType,
			setGlobalNozzleDiameter,
			setPrinterName,
			setViewMode,
			setVendor,
			setSelectedPrinterId,
			setScaleToastDismissed,
			setNozzleTypes,
			setProcessName,
			setNozzleDiameters,
			setFilamentSlots,
		],
	);
	return { applySavedPrinter };
}
