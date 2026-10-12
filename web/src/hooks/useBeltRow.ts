import { useMemo } from 'react';
import { beltRowShifts } from '../beltLayout';
import type { Dimensions } from '../dimensions';
import type { AppState, MainAppProps } from './useAppState';
import type { useObjectsView } from './useObjectsView';

export function useBeltRow(c: AppState & Pick<MainAppProps, never> & ReturnType<typeof useObjectsView>) {
	const { isBeltPrinter, hasObjectChoice, beltLineUp, keptObjects, objects, beltOrder, excludedObjects, beltGapMm, beltRowMode } = c;

	// A belt printer that lines a file's objects up: where each kept object goes (one after another, or
	// plate by plate for a multi-plate file), shown in the preview and used to size what will print.
	const rowLayout = useMemo(() => {
		if (!isBeltPrinter || !hasObjectChoice || !beltLineUp || keptObjects.length === 0) return null;
		const shifts = beltRowShifts(objects, beltOrder, excludedObjects, beltGapMm, beltRowMode);
		const spans = keptObjects.map((o) => ({
			x0: o.center_x_mm - o.width_mm / 2 + shifts[o.index].dx,
			x1: o.center_x_mm + o.width_mm / 2 + shifts[o.index].dx,
			y0: o.center_y_mm - o.depth_mm / 2 + shifts[o.index].dy,
			y1: o.center_y_mm + o.depth_mm / 2 + shifts[o.index].dy,
		}));
		const extent: Dimensions = {
			x: Math.max(...spans.map((s) => s.x1)) - Math.min(...spans.map((s) => s.x0)),
			y: Math.max(...spans.map((s) => s.y1)) - Math.min(...spans.map((s) => s.y0)),
			z: Math.max(...keptObjects.map((o) => o.height_mm)),
		};
		return { shifts, extent };
	}, [isBeltPrinter, hasObjectChoice, beltLineUp, keptObjects, objects, beltOrder, excludedObjects, beltGapMm, beltRowMode]);
	return { rowLayout };
}
