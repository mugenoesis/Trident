import { useCallback } from 'react';
import { deleteImportedProfile, listImportedProfiles, listProfiles } from '../api';
import { defaultSlotColor, MAX_FILAMENT_SLOTS } from '../appHelpers';
import type { AppState, MainAppProps } from './useAppState';
import type { useProfileHandlers } from './useProfileHandlers';

export function useSlotHandlers(c: AppState & Pick<MainAppProps, never> & ReturnType<typeof useProfileHandlers>) {
	const { setMaterialDialog, setProfiles, handleFilamentSlotChange, setFilamentSlots, setViewMode } = c;

	// A material was created or edited: reload the list first so the slot's
	// choice exists in it, then select it.
	const handleMaterialSaved = useCallback(
		(slot: number, name: string) => {
			setMaterialDialog(null);
			listProfiles()
				.then((list) => {
					setProfiles(list);
					handleFilamentSlotChange(slot, { profile: name });
				})
				.catch(() => handleFilamentSlotChange(slot, { profile: name }));
		},
		[handleFilamentSlotChange, setProfiles, setMaterialDialog],
	);

	// Delete one of the user's own materials; the slot falls back to the
	// material it was based on, or the first one available.
	const handleDeleteCustomFilament = useCallback(
		async (slot: number, name: string) => {
			try {
				const imported = await listImportedProfiles();
				const parent = imported.find((p) => p.kind === 'filament' && p.name === name)?.inherits ?? null;
				await deleteImportedProfile('filament', name);
				const list = await listProfiles();
				setProfiles(list);
				const stillThere = (n: string | null) => n !== null && list.some((p) => p.kind === 'filament' && p.name === n);
				const fallback = stillThere(parent) ? parent : (list.find((p) => p.kind === 'filament')?.name ?? '');
				handleFilamentSlotChange(slot, { profile: fallback as string });
			} catch (err) {
				alert(`Failed to delete the material: ${(err as Error).message}`);
			}
		},
		[handleFilamentSlotChange, setProfiles],
	);

	// A fresh slot's nozzle diameter/type defaults from the last existing
	// slot (adding a physical head is usually adding one similar to what you
	// already have) -- fully editable afterward either way.
	const addFilamentSlot = useCallback(() => {
		setFilamentSlots((prev) => {
			if (prev.length >= MAX_FILAMENT_SLOTS) return prev;
			const last = prev[prev.length - 1];
			return [
				...prev,
				{
					profile: '',
					color: defaultSlotColor(prev.length),
					nozzleDiameter: last?.nozzleDiameter ?? 0.4,
					nozzleType: last?.nozzleType ?? 'undefine',
				},
			];
		});
		setViewMode('model');
	}, [setFilamentSlots, setViewMode]);

	const removeFilamentSlot = useCallback(
		(index: number) => {
			setFilamentSlots((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== index) : prev));
			setViewMode('model');
		},
		[setFilamentSlots, setViewMode],
	);
	return { handleMaterialSaved, handleDeleteCustomFilament, addFilamentSlot, removeFilamentSlot };
}
