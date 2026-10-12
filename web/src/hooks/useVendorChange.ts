import { useCallback } from 'react';
import { buildFilamentSlots } from '../appHelpers';
import type { AppState, MainAppProps } from './useAppState';

export function useVendorChange(c: AppState & Pick<MainAppProps, never>) {
	const {
		setVendor,
		setPrinterName,
		setProcessName,
		setFilamentSlots,
		setBedSize,
		setNozzleDiameters,
		setNozzleTypes,
		setGlobalNozzleDiameter,
		setGlobalNozzleType,
		setSelectedPrinterId,
		setViewMode,
	} = c;

	const handleVendorChange = useCallback(
		(v: string) => {
			setVendor(v);
			setPrinterName('');
			setProcessName('');
			setFilamentSlots(buildFilamentSlots(1, ''));
			setBedSize(null);
			setNozzleDiameters([]);
			setNozzleTypes([]);
			setGlobalNozzleDiameter('');
			setGlobalNozzleType('undefine');
			setSelectedPrinterId(null);
			setViewMode('model');
		},
		[
			setNozzleDiameters,
			setBedSize,
			setGlobalNozzleDiameter,
			setPrinterName,
			setViewMode,
			setVendor,
			setSelectedPrinterId,
			setNozzleTypes,
			setProcessName,
			setFilamentSlots,
			setGlobalNozzleType,
		],
	);
	return { handleVendorChange };
}
