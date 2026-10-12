import { useEffect } from 'react';
import { listMaterialProfiles, listSettingsProfiles } from '../api';
import type { AppState, MainAppProps } from './useAppState';
import type { useProfileApply } from './useProfileApply';

export function useProfileLists(c: AppState & Pick<MainAppProps, never> & ReturnType<typeof useProfileApply>) {
	const {
		selectedPrinterId,
		setMaterials,
		setSelectedMaterialId,
		pendingLastMaterialId,
		applyMaterialProfile,
		setRestorationDone,
		setSettingsProfiles,
		setSelectedSettingsProfileId,
		pendingLastSettingsProfileId,
		applySettingsProfile,
		setSettingsRestorationDone,
	} = c;

	// A saved printer's material profiles only matter while that printer is
	// selected -- reload (and drop any stale selection) whenever it changes.
	// biome-ignore lint/correctness/useExhaustiveDependencies: the state setters and refs come in through the hook's context object, so Biome cannot see they are stable; the refs are read when it runs, on purpose
	useEffect(() => {
		if (!selectedPrinterId) {
			setMaterials([]);
			setSelectedMaterialId(null);
			return;
		}
		setSelectedMaterialId(null);
		listMaterialProfiles(selectedPrinterId)
			.then((list) => {
				setMaterials(list);
				// Only ever meaningful for the one materials fetch that follows a
				// restored printer selection (below) -- consumed once so a later,
				// manual printer switch doesn't try to reapply a stale id.
				const pendingId = pendingLastMaterialId.current;
				pendingLastMaterialId.current = null;
				const match = pendingId ? list.find((m) => m.id === pendingId) : undefined;
				if (match) applyMaterialProfile(match);
			})
			.catch(() => setMaterials([]))
			.finally(() => setRestorationDone(true));
	}, [selectedPrinterId, applyMaterialProfile]);

	// Same idea for settings profiles, restored independently of materials
	// (a different id in AuthStatus, applied via its own pending ref).
	// biome-ignore lint/correctness/useExhaustiveDependencies: the state setters and refs come in through the hook's context object, so Biome cannot see they are stable; the refs are read when it runs, on purpose
	useEffect(() => {
		if (!selectedPrinterId) {
			setSettingsProfiles([]);
			setSelectedSettingsProfileId(null);
			return;
		}
		setSelectedSettingsProfileId(null);
		listSettingsProfiles(selectedPrinterId)
			.then((list) => {
				setSettingsProfiles(list);
				const pendingId = pendingLastSettingsProfileId.current;
				pendingLastSettingsProfileId.current = null;
				const match = pendingId ? list.find((p) => p.id === pendingId) : undefined;
				if (match) applySettingsProfile(match);
			})
			.catch(() => setSettingsProfiles([]))
			.finally(() => setSettingsRestorationDone(true));
	}, [selectedPrinterId, applySettingsProfile]);
}
