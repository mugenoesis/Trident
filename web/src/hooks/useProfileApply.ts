import { useCallback } from 'react';
import { defaultSlotColor } from '../appHelpers';
import type { MaterialProfileRecord, SettingsProfileRecord } from '../types';
import type { AppState, MainAppProps } from './useAppState';

export function useProfileApply(c: AppState & Pick<MainAppProps, never>) {
	const {
		setSelectedMaterialId,
		nozzleDiametersRef,
		nozzleTypesRef,
		setFilamentSlots,
		setViewMode,
		appliedSettingsProfileRef,
		setSelectedSettingsProfileId,
		setQuickSettings,
		setAdvancedOverrides,
		setProcessName,
	} = c;

	// biome-ignore lint/correctness/useExhaustiveDependencies: the state setters and refs come in through the hook's context object, so Biome cannot see they are stable; the refs are read when it runs, on purpose
	const applyMaterialProfile = useCallback((material: MaterialProfileRecord) => {
		setSelectedMaterialId(material.id);
		if (material.filament_profiles && material.filament_profiles.length > 0) {
			// A material profile doesn't save nozzle diameter/type (those are a
			// property of the physical printer/head, not the material) -- keep
			// whatever's already dialed in per slot where possible, falling back
			// to the catalog's own defaults for any newly-appearing slot.
			const diameters = nozzleDiametersRef.current;
			const types = nozzleTypesRef.current;
			setFilamentSlots((prev) =>
				material.filament_profiles!.map((profile, i) => ({
					profile,
					color: material.filament_colors?.[i] ?? defaultSlotColor(i),
					nozzleDiameter: prev[i]?.nozzleDiameter ?? diameters[i] ?? diameters[diameters.length - 1] ?? 0.4,
					nozzleType: prev[i]?.nozzleType ?? types[i] ?? types[types.length - 1] ?? 'undefine',
				})),
			);
		}
		setViewMode('model');
	}, []);

	// biome-ignore lint/correctness/useExhaustiveDependencies: the state setters and refs come in through the hook's context object, so Biome cannot see they are stable; the refs are read when it runs, on purpose
	const applySettingsProfile = useCallback((profile: SettingsProfileRecord) => {
		appliedSettingsProfileRef.current = true;
		setSelectedSettingsProfileId(profile.id);
		setQuickSettings((prev) => ({ ...prev, ...profile.quick_settings }));
		setAdvancedOverrides(profile.advanced_overrides);
		if (profile.process_profile) setProcessName(profile.process_profile);
		setViewMode('model');
	}, []);
	return { applyMaterialProfile, applySettingsProfile };
}
