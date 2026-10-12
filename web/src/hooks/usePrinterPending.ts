import { useCallback, useEffect } from 'react';
import { listProfiles } from '../api';
import { IMPORTED_VENDOR } from '../appHelpers';
import type { AppState, MainAppProps } from './useAppState';
import type { usePrinterChoice } from './usePrinterChoice';

export function usePrinterPending(c: AppState & Pick<MainAppProps, never> & ReturnType<typeof usePrinterChoice>) {
	const { setPrinterDialog, setProfiles, setVendor, setPendingPrinter, pendingPrinter, vendor, profiles, handlePrinterChange } = c;

	// A printer was made or changed: reload the list, then select it (the list has to contain it first).
	const handlePrinterSaved = useCallback(
		(name: string) => {
			setPrinterDialog(null);
			listProfiles()
				.then((list) => {
					setProfiles(list);
					setVendor(IMPORTED_VENDOR);
					setPendingPrinter(name);
				})
				.catch(() => {
					setVendor(IMPORTED_VENDOR);
					setPendingPrinter(name);
				});
		},
		[setProfiles, setPendingPrinter, setPrinterDialog, setVendor],
	);
	useEffect(() => {
		if (
			pendingPrinter &&
			vendor === IMPORTED_VENDOR &&
			profiles.some((p) => p.kind === 'machine' && p.vendor === IMPORTED_VENDOR && p.name === pendingPrinter)
		) {
			handlePrinterChange(pendingPrinter);
			setPendingPrinter(null);
		}
	}, [pendingPrinter, vendor, profiles, handlePrinterChange, setPendingPrinter]);
	return { handlePrinterSaved };
}
