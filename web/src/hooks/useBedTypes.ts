import { useEffect } from 'react';
import { getProfileDetail } from '../api';
import { pickBedType, supportedBedTypes } from '../bedTypes';
import type { AppState, MainAppProps } from './useAppState';

export function useBedTypes(c: AppState & Pick<MainAppProps, never>) {
	const { filamentSlots, setAllowedBedTypes, profiles, allowedBedTypes, quickSettings, setQuickSettings, printerDefaultBed } = c;

	// The materials in use decide which build plates make sense: read their
	// supported plates, and if the current plate is not one of them move to one
	// that is (the printer's own default when the material allows it).
	const slotProfilesKey = filamentSlots
		.map((s) => s.profile)
		.filter(Boolean)
		.join('\u0001');
	useEffect(() => {
		const names = [...new Set(slotProfilesKey ? slotProfilesKey.split('\u0001') : [])];
		if (names.length === 0) {
			setAllowedBedTypes(null);
			return;
		}
		let live = true;
		Promise.all(
			names.map((name) => {
				const vendorOf = profiles.find((p) => p.kind === 'filament' && p.name === name)?.vendor;
				return vendorOf ? getProfileDetail(vendorOf, 'filament', name).then((d) => d.data) : Promise.resolve(null);
			}),
		)
			.then((details) => {
				if (!live) return;
				const known = details.filter((d): d is Record<string, unknown> => d !== null);
				setAllowedBedTypes(known.length === names.length ? supportedBedTypes(known) : null);
			})
			.catch(() => live && setAllowedBedTypes(null));
		return () => {
			live = false;
		};
	}, [slotProfilesKey, profiles, setAllowedBedTypes]);
	useEffect(() => {
		if (allowedBedTypes && allowedBedTypes.length > 0 && !allowedBedTypes.includes(quickSettings.curr_bed_type)) {
			setQuickSettings((prev) => ({ ...prev, curr_bed_type: pickBedType(allowedBedTypes, printerDefaultBed) }));
		}
	}, [allowedBedTypes, printerDefaultBed, quickSettings.curr_bed_type, setQuickSettings]);
	return { slotProfilesKey };
}
