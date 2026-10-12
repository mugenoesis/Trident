import { useEffect } from 'react';
import type { AppState, MainAppProps } from './useAppState';

export function useResetOnNewFile(c: AppState & Pick<MainAppProps, never>) {
	const { setExcludedObjects, setBeltRowMode, setBeltOrder, plateInfo } = c;

	// A newly loaded file starts with everything selected, in file order.
	useEffect(() => {
		setExcludedObjects(new Set());
		setBeltRowMode('plates');
		// Plate by plate (then file order within a plate), so a multi-plate file goes along the belt plate 1, 2, 3.
		setBeltOrder([...(plateInfo?.objects ?? [])].sort((a, b) => a.plate - b.plate || a.index - b.index).map((o) => o.index));
	}, [plateInfo, setBeltOrder, setBeltRowMode, setExcludedObjects]);
}
