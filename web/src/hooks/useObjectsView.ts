import { useMemo } from 'react';
import type { ObjectInfo } from '../types';
import type { AppState, MainAppProps } from './useAppState';

export function useObjectsView(c: AppState & Pick<MainAppProps, never>) {
	const {
		plateInfo,
		bedSize,
		beltLineUp,
		copies,
		excludedObjects,
		file,
		modelId,
		printerName,
		dimensions,
		plateIndex,
		beltOrder,
		beltGapMm,
		beltRowMode,
		placement,
	} = c;

	const objects: ObjectInfo[] = useMemo(() => plateInfo?.objects ?? [], [plateInfo]);
	const hasObjectChoice = objects.length > 1;
	const isBeltPrinter = bedSize?.beltPrinterInfiniteY === true;
	// On a belt printer every kept object goes in one row along the belt, so
	// which plate it came from no longer matters and the plate picker is moot.
	const beltRowActive = isBeltPrinter && ((hasObjectChoice && beltLineUp) || copies > 1);
	const keptObjects = useMemo(() => objects.filter((o) => !excludedObjects.has(o.index)), [objects, excludedObjects]);
	// Position sliders: a model on a chosen printer, on a single plate, and not
	// already laid out by the belt row.
	const readyToPlace = Boolean(file && modelId && printerName && bedSize && dimensions) && !beltRowActive && copies === 1;
	const multiPlate = (plateInfo?.plates.length ?? 1) > 1;
	const showPositionPanel = readyToPlace && !multiPlate;
	// The Rotate and move window also works on one plate of a multi-plate file (once a plate is chosen).
	const showRotateMove = readyToPlace && (!multiPlate || plateIndex !== null);
	const objectSelectionSignature = JSON.stringify({
		excluded: hasObjectChoice ? [...excludedObjects].sort((x, y) => x - y) : [],
		row: beltRowActive ? { order: beltOrder.filter((i) => !excludedObjects.has(i)), gap: beltGapMm, mode: beltRowMode } : null,
		placement: showPositionPanel ? placement : null,
		copies,
	});
	return {
		objects,
		hasObjectChoice,
		isBeltPrinter,
		beltRowActive,
		keptObjects,
		readyToPlace,
		multiPlate,
		showPositionPanel,
		showRotateMove,
		objectSelectionSignature,
	};
}
