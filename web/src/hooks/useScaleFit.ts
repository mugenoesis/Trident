import { canScaleFile, computeFitScale, type Dimensions } from '../dimensions';
import type { AppState, MainAppProps } from './useAppState';
import type { useBeltRow } from './useBeltRow';
import type { useObjectsView } from './useObjectsView';

export function useScaleFit(c: AppState & Pick<MainAppProps, never> & ReturnType<typeof useObjectsView> & ReturnType<typeof useBeltRow>) {
	const { beltRowActive, rowLayout, copies, beltGapMm, keptObjects, dimensions, bedSize, printerName, file, scaleToastDismissed } = c;

	// What will actually print. A belt row is the lined-up layout, repeated per copy; for any other
	// multi-plate file the viewer's combined extent across plates means nothing, so no fit
	// suggestion is made at all.
	const fitDimensions: Dimensions | null =
		beltRowActive && rowLayout
			? { x: rowLayout.extent.x, y: rowLayout.extent.y * copies + beltGapMm * (copies - 1), z: rowLayout.extent.z }
			: beltRowActive && keptObjects.length > 0
				? {
						x: Math.max(...keptObjects.map((o) => o.width_mm)),
						y: keptObjects.reduce((sum, o) => sum + o.depth_mm, 0) * copies + beltGapMm * (keptObjects.length * copies - 1),
						z: Math.max(...keptObjects.map((o) => o.height_mm)),
					}
				: beltRowActive && dimensions
					? { x: dimensions.x, y: dimensions.y * copies + beltGapMm * (copies - 1), z: dimensions.z }
					: dimensions;
	const fitScale = fitDimensions && bedSize && printerName ? computeFitScale(fitDimensions, bedSize) : null;
	const scalable = file ? canScaleFile(file) : true;
	const showScaleToast = fitScale !== null && !scaleToastDismissed && scalable;
	return { fitDimensions, fitScale, scalable, showScaleToast };
}
