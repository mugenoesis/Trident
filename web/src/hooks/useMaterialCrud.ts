import { useCallback } from 'react';
import { createMaterialProfile, deleteMaterialProfile, duplicateMaterialProfile, updateMaterialProfile } from '../api';
import type { AppState, MainAppProps } from './useAppState';

export function useMaterialCrud(c: AppState & Pick<MainAppProps, never>) {
	const { selectedPrinterId, filamentSlots, setMaterials, setSelectedMaterialId, selectedMaterialId } = c;

	const handleSaveMaterial = useCallback(
		(name: string) => {
			if (!selectedPrinterId) return Promise.reject(new Error('Select a saved printer first'));
			return createMaterialProfile(selectedPrinterId, {
				name,
				filament_profiles: filamentSlots.map((s) => s.profile),
				filament_colors: filamentSlots.map((s) => s.color),
			}).then((material) => {
				setMaterials((prev) => [...prev, material]);
				setSelectedMaterialId(material.id);
			});
		},
		[selectedPrinterId, filamentSlots, setMaterials, setSelectedMaterialId],
	);

	const handleDeleteMaterial = useCallback(
		(id: string) => {
			if (!selectedPrinterId) return;
			deleteMaterialProfile(selectedPrinterId, id)
				.then(() => {
					setMaterials((prev) => prev.filter((m) => m.id !== id));
					setSelectedMaterialId((prev) => (prev === id ? null : prev));
				})
				.catch((err: Error) => alert(`Failed to delete material profile: ${err.message}`));
		},
		[selectedPrinterId, setMaterials, setSelectedMaterialId],
	);

	const handleDeselectMaterial = useCallback(() => setSelectedMaterialId(null), [setSelectedMaterialId]);

	// "Update mode": overwrites the already-selected material profile with
	// whatever's currently dialed in, instead of creating a new one.
	const handleUpdateMaterial = useCallback(() => {
		if (!selectedPrinterId || !selectedMaterialId) {
			return Promise.reject(new Error('Select a material profile first'));
		}
		return updateMaterialProfile(selectedPrinterId, selectedMaterialId, {
			filament_profiles: filamentSlots.map((s) => s.profile),
			filament_colors: filamentSlots.map((s) => s.color),
		}).then((material) => {
			setMaterials((prev) => prev.map((m) => (m.id === material.id ? material : m)));
		});
	}, [selectedPrinterId, selectedMaterialId, filamentSlots, setMaterials]);

	const handleRenameMaterial = useCallback(
		(id: string, name: string) => {
			if (!selectedPrinterId) return Promise.reject(new Error('No printer selected'));
			return updateMaterialProfile(selectedPrinterId, id, { name }).then((material) => {
				setMaterials((prev) => prev.map((m) => (m.id === material.id ? material : m)));
			});
		},
		[selectedPrinterId, setMaterials],
	);

	const handleDuplicateMaterial = useCallback(
		(id: string) => {
			if (!selectedPrinterId) return;
			duplicateMaterialProfile(selectedPrinterId, id)
				.then((material) => setMaterials((prev) => [...prev, material]))
				.catch((err: Error) => alert(`Failed to duplicate material profile: ${err.message}`));
		},
		[selectedPrinterId, setMaterials],
	);
	return {
		handleSaveMaterial,
		handleDeleteMaterial,
		handleDeselectMaterial,
		handleUpdateMaterial,
		handleRenameMaterial,
		handleDuplicateMaterial,
	};
}
