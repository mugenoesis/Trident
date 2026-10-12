import { useEffect } from 'react';
import type { AppState, MainAppProps } from './useAppState';

export function usePrimeTower(c: AppState & Pick<MainAppProps, never>) {
	const { filamentSlots, bedSize, setQuickSettings } = c;

	// A color change can only happen at all once there's more than one
	// filament slot configured on the printer (whether that's several heads
	// or several AMS-style slots feeding one shared nozzle) -- crossing that
	// threshold turns the prime/wipe tower on by default, since leftover
	// filament on the nozzle from the previous color would otherwise show up
	// in the next layer. Deliberately keyed on the true/false threshold
	// itself, not the raw slot count, so it fires once going from a single
	// material to several, not on every subsequent slot added/removed while
	// already multi-material -- the checkbox in QuickSettings stays a normal
	// toggle either way, this is just the starting point.
	//
	// Never for a belt printer: fdm_belt_common.json sets
	// purge_in_prime_tower=0 and belt mode has its own dedicated
	// purge-into-object system (BeltPurge.cpp/Print::has_belt_purge_tower(),
	// replacing the classic wipe tower) that a forced classic prime tower
	// would conflict with. Multi-extruder belt printers are essentially
	// nonexistent in practice, so this only ever skips a default that would
	// otherwise never even apply.
	const hasMultipleFilamentSlots = filamentSlots.length > 1 && !bedSize?.beltPrinterInfiniteY;
	useEffect(() => {
		if (hasMultipleFilamentSlots) {
			setQuickSettings((prev) => (prev.enable_prime_tower === '1' ? prev : { ...prev, enable_prime_tower: '1' }));
		}
	}, [hasMultipleFilamentSlots, setQuickSettings]);
	return { hasMultipleFilamentSlots };
}
