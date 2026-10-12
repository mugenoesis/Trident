import { useMemo } from 'react';
import { computeSliceSignature } from '../appHelpers';
import type { AppState, MainAppProps } from './useAppState';
import type { useObjectsView } from './useObjectsView';
import type { usePlateShown } from './usePlateShown';
import type { useRoles } from './useRoles';
import type { useSelection } from './useSelection';

export function useSignature(
	c: AppState &
		Pick<MainAppProps, never> &
		ReturnType<typeof useSelection> &
		ReturnType<typeof useRoles> &
		ReturnType<typeof useObjectsView> &
		ReturnType<typeof usePlateShown>,
) {
	const {
		isMultiHeadPrinter,
		filamentSlots,
		globalNozzleDiameter,
		globalNozzleType,
		modelId,
		printerName,
		processName,
		effectiveFilamentProfiles,
		plateIndex,
		quickSettings,
		advancedOverrides,
		objectSelectionSignature,
		roleNozzleAssignments,
		currentJob,
		lastSlicedSignature,
		showPlatePicker,
		hasObjectChoice,
		keptObjects,
		allRolesAssigned,
	} = c;

	// Part of the slice signature (below) so a nozzle diameter/type edit
	// counts as "you changed something" the same way any other slice-
	// affecting setting does.
	const nozzleSettingsSignature = isMultiHeadPrinter
		? JSON.stringify(filamentSlots.map((s) => [s.nozzleDiameter, s.nozzleType]))
		: JSON.stringify({ globalNozzleDiameter, globalNozzleType });

	const currentSignature = useMemo(
		() =>
			computeSliceSignature(
				modelId,
				printerName,
				processName,
				effectiveFilamentProfiles,
				plateIndex,
				quickSettings,
				advancedOverrides,
				nozzleSettingsSignature,
				objectSelectionSignature,
				roleNozzleAssignments,
			),
		[
			modelId,
			printerName,
			processName,
			effectiveFilamentProfiles,
			plateIndex,
			quickSettings,
			advancedOverrides,
			nozzleSettingsSignature,
			objectSelectionSignature,
			roleNozzleAssignments,
		],
	);
	// Only a *successful* prior slice blocks re-slicing -- a failed job with
	// unchanged settings should still be retryable (e.g. a transient error).
	const alreadySliced = currentJob?.status === 'succeeded' && lastSlicedSignature === currentSignature;
	const filamentSlotsFilled = filamentSlots.every((s) => s.profile);
	// A multi-plate file requires an explicit pick before slicing is enabled
	// -- there's no good "slice all of them" default once a specific plate
	// picker exists (see plan: pre-slice picker, not slice-everything).
	const plateChosenIfNeeded = !showPlatePicker || plateIndex !== null;
	// Something must be left to print -- and, when one plate is picked, on that plate.
	const objectSelectionOk =
		!hasObjectChoice ||
		(keptObjects.length > 0 && (showPlatePicker && plateIndex !== null ? keptObjects.some((o) => o.plate === plateIndex) : true));
	const canSlice =
		Boolean(modelId && printerName && processName && allRolesAssigned) && plateChosenIfNeeded && objectSelectionOk && !alreadySliced;
	return {
		nozzleSettingsSignature,
		currentSignature,
		alreadySliced,
		filamentSlotsFilled,
		plateChosenIfNeeded,
		objectSelectionOk,
		canSlice,
	};
}
