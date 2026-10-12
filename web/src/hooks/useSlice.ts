import { useCallback } from 'react';
import { createJob } from '../api';
import { jobRequestOf, nozzleOverrides, quickOverrides, remapPairsOf } from '../sliceRequest';
import type { AppState, MainAppProps } from './useAppState';
import type { useObjectsView } from './useObjectsView';
import type { useRoles } from './useRoles';
import type { useSelection } from './useSelection';
import type { useSignature } from './useSignature';

export function useSlice(
	c: AppState &
		Pick<MainAppProps, never> &
		ReturnType<typeof useRoles> &
		ReturnType<typeof useSignature> &
		ReturnType<typeof useSelection> &
		ReturnType<typeof useObjectsView>,
) {
	const {
		modelId,
		printerName,
		processName,
		allRolesAssigned,
		plateChosenIfNeeded,
		objectSelectionOk,
		setSlicing,
		setViewMode,
		setLastSlicedSignature,
		currentSignature,
		advancedOverrides,
		quickSettings,
		isMultiHeadPrinter,
		filamentSlots,
		globalNozzleDiameter,
		globalNozzleType,
		roleNozzleAssignments,
		viewerRef,
		effectiveFilamentProfiles,
		plateIndex,
		showPositionPanel,
		placement,
		copies,
		hasObjectChoice,
		excludedObjects,
		beltRowActive,
		beltOrder,
		beltGapMm,
		beltRowMode,
		setCurrentJob,
	} = c;

	// biome-ignore lint/correctness/useExhaustiveDependencies: the state setters and refs come in through the hook's context object, so Biome cannot see they are stable; the refs are read when it runs, on purpose
	const handleSlice = useCallback(() => {
		if (!modelId || !printerName || !processName || !allRolesAssigned || !plateChosenIfNeeded || !objectSelectionOk) return;
		setSlicing(true);
		setViewMode('model');
		setLastSlicedSignature(currentSignature);
		const overrides: Record<string, string> = {
			...quickOverrides(quickSettings, advancedOverrides),
			...nozzleOverrides(isMultiHeadPrinter, filamentSlots, advancedOverrides, globalNozzleDiameter, globalNozzleType),
		};
		const remapPairs = remapPairsOf(roleNozzleAssignments);
		const needsRemap = remapPairs.length > 0;
		if (needsRemap) overrides.remap_filament_extruder = remapPairs.join(',');
		// Best-effort: a snapshot of exactly what's on screen right now (the
		// file's own colors, or the user's chosen nozzle-to-slot substitution)
		// gets embedded into the gcode as its preview thumbnail server-side --
		// see api/app/gcode_thumbnail.py for why this happens client-side
		// instead of in the slicer engine. Strips the "data:image/png;base64,"
		// prefix; a capture failure (nothing loaded yet, tainted canvas) just
		// means no preview, not a blocked slice.
		const previewDataUrl = viewerRef.current?.capturePreview();
		const previewImageBase64 = previewDataUrl?.split(',')[1];
		const order = beltOrder.filter((i) => !excludedObjects.has(i));
		createJob(
			jobRequestOf({
				modelId,
				printerName,
				processName,
				previewImageBase64,
				// Confirmed via direct CLI testing: --load-filaments position N
				// always means physical extruder N (1-based) -- once a remap is in
				// play, the file can end up using non-sequential/sparse extruder
				// numbers (e.g. 2 and 4), and the array must be DENSE, sized to
				// cover every configured physical slot, not just "as many as the
				// file's own role count" (that narrower rule is what the no-remap
				// path below still uses, and remains correct for it: today's files
				// always use sequential extruders from 1).
				filamentProfiles: needsRemap ? filamentSlots.map((s) => s.profile) : effectiveFilamentProfiles,
				overrides,
				plateIndex,
				placement: showPositionPanel ? placement : null,
				copies,
				excludedObjects: hasObjectChoice ? [...excludedObjects].sort((x, y) => x - y) : undefined,
				beltLayout: beltRowActive ? { order, gap_mm: beltGapMm, mode: beltRowMode } : undefined,
			}),
		)
			.then(setCurrentJob)
			.catch((err: Error) => {
				setSlicing(false);
				alert(`Failed to start slicing job: ${err.message}`);
			});
	}, [
		modelId,
		printerName,
		processName,
		allRolesAssigned,
		plateChosenIfNeeded,
		objectSelectionOk,
		hasObjectChoice,
		showPositionPanel,
		placement,
		copies,
		excludedObjects,
		beltRowActive,
		beltOrder,
		beltGapMm,
		beltRowMode,
		effectiveFilamentProfiles,
		plateIndex,
		quickSettings,
		advancedOverrides,
		filamentSlots,
		roleNozzleAssignments,
		isMultiHeadPrinter,
		globalNozzleDiameter,
		globalNozzleType,
		currentSignature,
	]);
	return { handleSlice };
}
