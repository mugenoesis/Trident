import { useCallback } from 'react';
import { createSettingsProfile, deleteSettingsProfile, duplicateSettingsProfile, updateSettingsProfile } from '../api';
import type { AppState, MainAppProps } from './useAppState';

export function useSettingsCrud(c: AppState & Pick<MainAppProps, never>) {
	const {
		selectedPrinterId,
		quickSettings,
		advancedOverrides,
		processName,
		setSettingsProfiles,
		setSelectedSettingsProfileId,
		selectedSettingsProfileId,
	} = c;

	const handleSaveSettingsProfile = useCallback(
		(name: string) => {
			if (!selectedPrinterId) return Promise.reject(new Error('Select a saved printer first'));
			return createSettingsProfile(selectedPrinterId, {
				name,
				quick_settings: quickSettings as unknown as Record<string, string>,
				advanced_overrides: advancedOverrides,
				process_profile: processName || null,
			}).then((profile) => {
				setSettingsProfiles((prev) => [...prev, profile]);
				setSelectedSettingsProfileId(profile.id);
			});
		},
		[selectedPrinterId, quickSettings, advancedOverrides, processName, setSelectedSettingsProfileId, setSettingsProfiles],
	);

	const handleDeleteSettingsProfile = useCallback(
		(id: string) => {
			if (!selectedPrinterId) return;
			deleteSettingsProfile(selectedPrinterId, id)
				.then(() => {
					setSettingsProfiles((prev) => prev.filter((p) => p.id !== id));
					setSelectedSettingsProfileId((prev) => (prev === id ? null : prev));
				})
				.catch((err: Error) => alert(`Failed to delete settings profile: ${err.message}`));
		},
		[selectedPrinterId, setSelectedSettingsProfileId, setSettingsProfiles],
	);

	const handleDeselectSettingsProfile = useCallback(() => setSelectedSettingsProfileId(null), [setSelectedSettingsProfileId]);

	// "Update mode": overwrites the already-selected settings profile with
	// whatever's currently dialed in, instead of creating a new one.
	const handleUpdateSettingsProfile = useCallback(() => {
		if (!selectedPrinterId || !selectedSettingsProfileId) {
			return Promise.reject(new Error('Select a settings profile first'));
		}
		return updateSettingsProfile(selectedPrinterId, selectedSettingsProfileId, {
			quick_settings: quickSettings as unknown as Record<string, string>,
			advanced_overrides: advancedOverrides,
			process_profile: processName || null,
		}).then((profile) => {
			setSettingsProfiles((prev) => prev.map((p) => (p.id === profile.id ? profile : p)));
		});
	}, [selectedPrinterId, selectedSettingsProfileId, quickSettings, advancedOverrides, processName, setSettingsProfiles]);

	const handleRenameSettingsProfile = useCallback(
		(id: string, name: string) => {
			if (!selectedPrinterId) return Promise.reject(new Error('No printer selected'));
			return updateSettingsProfile(selectedPrinterId, id, { name }).then((profile) => {
				setSettingsProfiles((prev) => prev.map((p) => (p.id === profile.id ? profile : p)));
			});
		},
		[selectedPrinterId, setSettingsProfiles],
	);

	const handleDuplicateSettingsProfile = useCallback(
		(id: string) => {
			if (!selectedPrinterId) return;
			duplicateSettingsProfile(selectedPrinterId, id)
				.then((profile) => setSettingsProfiles((prev) => [...prev, profile]))
				.catch((err: Error) => alert(`Failed to duplicate settings profile: ${err.message}`));
		},
		[selectedPrinterId, setSettingsProfiles],
	);
	return {
		handleSaveSettingsProfile,
		handleDeleteSettingsProfile,
		handleDeselectSettingsProfile,
		handleUpdateSettingsProfile,
		handleRenameSettingsProfile,
		handleDuplicateSettingsProfile,
	};
}
