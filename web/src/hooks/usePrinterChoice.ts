import { useCallback } from 'react';
import { getProfileDetail } from '../api';
import { buildFilamentSlots, firstOfKind, parsedNozzleDiameters, parsedNozzleTypes, profileNameFrom } from '../appHelpers';
import { parseBedSize } from '../dimensions';
import type { AppState, MainAppProps } from './useAppState';

export function usePrinterChoice(c: AppState & Pick<MainAppProps, never>) {
	const {
		setPrinterName,
		setProcessName,
		setFilamentSlots,
		setBedSize,
		setNozzleDiameters,
		setNozzleTypes,
		setGlobalNozzleDiameter,
		setGlobalNozzleType,
		setScaleToastDismissed,
		setSelectedPrinterId,
		setViewMode,
		vendor,
		profiles,
		setPrinterDefaultBed,
		schema,
		setQuickSettings,
	} = c;

	// Picking a printer resets process/material to that machine's own
	// defaults (default_print_profile / default_filament_profile) --
	// matches how OrcaSlicer itself behaves when you switch printers.
	const handlePrinterChange = useCallback(
		(name: string) => {
			setPrinterName(name);
			setProcessName('');
			setFilamentSlots(buildFilamentSlots(1, ''));
			setBedSize(null);
			setNozzleDiameters([]);
			setNozzleTypes([]);
			setGlobalNozzleDiameter('');
			setGlobalNozzleType('undefine');
			setScaleToastDismissed(false);
			setSelectedPrinterId(null);
			setViewMode('model');
			if (!vendor || !name) return;

			getProfileDetail(vendor, 'machine', name)
				.then((detail) => {
					const process = profileNameFrom(detail.data.default_print_profile, () => firstOfKind(profiles, vendor, name, 'process'));
					const filament = profileNameFrom(detail.data.default_filament_profile, () => firstOfKind(profiles, vendor, name, 'filament'));
					const diameters = parsedNozzleDiameters(detail.data);
					const types = parsedNozzleTypes(detail.data);
					setProcessName(process);
					// Always exactly 1 slot on a fresh printer/vendor pick -- the user
					// adds more via the "+" control in the Material section
					// (addFilamentSlot below) rather than it being derived from
					// whatever slot count this specific catalog profile happens to
					// define.
					setFilamentSlots(buildFilamentSlots(1, filament, diameters, types));
					setBedSize(parseBedSize(detail.data));
					// A newly picked printer starts on its own default plate; the
					// material check below then moves it if the material cannot use it.
					const printerBed = typeof detail.data.default_bed_type === 'string' ? detail.data.default_bed_type : null;
					setPrinterDefaultBed(printerBed);
					if (printerBed && schema.find((s) => s.key === 'curr_bed_type')?.enum_values?.includes(printerBed)) {
						setQuickSettings((prev) => ({ ...prev, curr_bed_type: printerBed }));
					}
					setNozzleDiameters(diameters);
					setNozzleTypes(types);
					setGlobalNozzleDiameter(diameters[0] != null ? String(diameters[0]) : '');
					setGlobalNozzleType(types[0] ?? 'undefine');
				})
				.catch(() => {
					setProcessName(firstOfKind(profiles, vendor, name, 'process'));
					setFilamentSlots(buildFilamentSlots(1, firstOfKind(profiles, vendor, name, 'filament')));
					setNozzleDiameters([]);
					setNozzleTypes([]);
				});
		},
		[
			vendor,
			profiles,
			schema,
			setGlobalNozzleDiameter,
			setGlobalNozzleType,
			setBedSize,
			setPrinterDefaultBed,
			setViewMode,
			setSelectedPrinterId,
			setScaleToastDismissed,
			setQuickSettings,
			setProcessName,
			setNozzleTypes,
			setPrinterName,
			setNozzleDiameters,
			setFilamentSlots,
		],
	);
	return { handlePrinterChange };
}
