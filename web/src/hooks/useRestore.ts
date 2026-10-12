import { useEffect } from 'react';
import type { AppState, MainAppProps } from './useAppState';
import type { useSavedPrinterApply } from './useSavedPrinterApply';

export function useRestore(
	c: AppState & Pick<MainAppProps, 'authStatus' | 'onUpdateLastSelection'> & ReturnType<typeof useSavedPrinterApply>,
) {
	const {
		printersLoaded,
		authStatus,
		printers,
		applySavedPrinter,
		setRestorationDone,
		setSettingsRestorationDone,
		restorationDone,
		settingsRestorationDone,
		onUpdateLastSelection,
		selectedPrinterId,
		selectedMaterialId,
		selectedSettingsProfileId,
	} = c;

	// Restores the account's last-selected printer, exactly once, right after
	// the printers list first loads (not on every later change to it, e.g.
	// after saving a new printer -- hence keying solely off `printersLoaded`
	// flipping true rather than the `printers` array itself).
	// biome-ignore lint/correctness/useExhaustiveDependencies: runs once the printer list has loaded; the saved-printer helpers it calls are not triggers
	useEffect(() => {
		if (!printersLoaded) return;
		const match = authStatus.last_printer_id ? printers.find((p) => p.id === authStatus.last_printer_id) : undefined;
		if (match) {
			applySavedPrinter(match);
			// Restoring a material/settings profile (if any) happens once this
			// printer's materials/settings-profiles lists load -- see the two
			// effects above, which mark restorationDone/settingsRestorationDone
			// when they settle.
		} else {
			setRestorationDone(true);
			setSettingsRestorationDone(true);
		}
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [printersLoaded]);

	// Persists the current printer/material/settings-profile selection as the
	// account's default for next time -- but not until the initial
	// restoration (above) has fully settled on both fronts, or this would
	// race it: e.g. save (printerId, null, null) right after the printer
	// restores but before its material/settings profile does, then lose to a
	// slower-finishing restore, permanently wiping the persisted id.
	useEffect(() => {
		if (!restorationDone || !settingsRestorationDone) return;
		onUpdateLastSelection(selectedPrinterId, selectedMaterialId, selectedSettingsProfileId).catch(() => {});
	}, [selectedPrinterId, selectedMaterialId, selectedSettingsProfileId, restorationDone, settingsRestorationDone, onUpdateLastSelection]);
}
