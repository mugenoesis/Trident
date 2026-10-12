import { useEffect } from 'react';
import { BELT_BRIM_TYPES } from '../components/QuickSettings';
import type { AppState, MainAppProps } from './useAppState';

export function useBrim(c: AppState & Pick<MainAppProps, never>) {
	const { bedSize, quickSettings, setQuickSettings } = c;

	// A brim type chosen earlier (or saved in a settings profile) that does not
	// exist on a belt printer goes back to "Profile default" rather than
	// silently doing something else.
	useEffect(() => {
		if (bedSize?.beltPrinterInfiniteY && quickSettings.brim_type && !BELT_BRIM_TYPES.includes(quickSettings.brim_type)) {
			setQuickSettings((prev) => ({ ...prev, brim_type: '' }));
		}
	}, [bedSize, quickSettings.brim_type, setQuickSettings]);
}
