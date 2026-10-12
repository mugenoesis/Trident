import { useMemo } from 'react';
import type { AppState, MainAppProps } from './useAppState';
import type { useObjectsView } from './useObjectsView';

export function usePlateShown(c: AppState & Pick<MainAppProps, never> & ReturnType<typeof useObjectsView>) {
	const { plateInfo, beltRowActive, plateIndex, objects } = c;

	const showPlatePicker = (plateInfo?.plates.length ?? 0) > 1 && !beltRowActive;
	// One plate of a multi-plate file at a time in the preview (not when a belt
	// row lays everything out end to end).
	const shownObjects = useMemo(
		() => (showPlatePicker && plateIndex !== null ? objects.filter((o) => o.plate === plateIndex).map((o) => o.index) : undefined),
		[showPlatePicker, plateIndex, objects],
	);
	return { showPlatePicker, shownObjects };
}
