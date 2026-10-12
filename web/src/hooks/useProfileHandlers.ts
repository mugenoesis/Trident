import { useCallback } from 'react';
import { listProfiles } from '../api';
import type { FilamentSlot } from '../appHelpers';
import type { QuickSettingsValues } from '../components/QuickSettings';
import type { AppState, MainAppProps } from './useAppState';

export function useProfileHandlers(c: AppState & Pick<MainAppProps, never>) {
	const { setProfiles, setProcessName, setViewMode, setFilamentSlots, setQuickSettings, setAdvancedOverrides } = c;

	// Reload the dropdowns after profiles were imported or deleted.
	const refreshProfiles = useCallback(() => {
		listProfiles()
			.then(setProfiles)
			.catch(() => {
				/* the existing list stays as it was */
			});
	}, [setProfiles]);

	// Any change to a slicing-relevant selection invalidates whatever G-code
	// preview might be showing -- it no longer reflects what a new slice
	// would produce, so drop back to the model view automatically.
	const handleProcessChange = useCallback(
		(name: string) => {
			setProcessName(name);
			setViewMode('model');
		},
		[setProcessName, setViewMode],
	);

	const handleFilamentSlotChange = useCallback(
		(index: number, patch: Partial<FilamentSlot>) => {
			setFilamentSlots((prev) => prev.map((slot, i) => (i === index ? { ...slot, ...patch } : slot)));
			setViewMode('model');
		},
		[setFilamentSlots, setViewMode],
	);

	// Note: unlike the printer/vendor handlers, this deliberately does NOT
	// clear selectedMaterialId -- once a material profile is selected,
	// tweaking settings is "update mode" (SavedPrinters shows an "Update
	// <name>" action that overwrites it) rather than instantly disowning the
	// selection. Picking a *different* material or the blank option is what
	// changes/clears selectedMaterialId (applyMaterialProfile / handleDeselect
	// MaterialProfile, below).
	const handleQuickSettingsChange = useCallback(
		(values: QuickSettingsValues) => {
			setQuickSettings(values);
			setViewMode('model');
		},
		[setQuickSettings, setViewMode],
	);

	const handleAdvancedOverridesChange = useCallback(
		(overrides: Record<string, string>) => {
			setAdvancedOverrides(overrides);
			setViewMode('model');
		},
		[setAdvancedOverrides, setViewMode],
	);
	return { refreshProfiles, handleProcessChange, handleFilamentSlotChange, handleQuickSettingsChange, handleAdvancedOverridesChange };
}
