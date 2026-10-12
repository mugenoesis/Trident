import { useEffect, useMemo } from 'react';
import { fileRolesFromInspection } from '../appHelpers';
import type { AppState, MainAppProps } from './useAppState';

export function useRoles(c: AppState & Pick<MainAppProps, never>) {
	const { plateInfo, setRoleNozzleAssignments, roleNozzleAssignments, filamentSlots } = c;

	const fileRoles = useMemo(() => fileRolesFromInspection(plateInfo), [plateInfo]);

	// Resets whenever a new file's roles are known -- a single-role file
	// (the common case: a plain STL, or a .3mf with no detected
	// multi-material info) defaults to the printer's first configured slot
	// so a plain single-color print needs no extra step, same as before
	// this feature existed; overridable via the nozzle-assignment UI below.
	// A genuinely multi-role file starts fully unassigned instead -- there's
	// no safe default mapping to guess (guessing wrong here is exactly what
	// crashed the CLI once already), so slicing stays blocked until every
	// role has an explicit, deliberate choice.
	useEffect(() => {
		setRoleNozzleAssignments(fileRoles.length === 1 ? [0] : fileRoles.map(() => null));
	}, [fileRoles, setRoleNozzleAssignments]);

	const allRolesAssigned = roleNozzleAssignments.every((slotIdx) => slotIdx !== null && filamentSlots[slotIdx]?.profile);
	// Exactly one filament per file role, chosen from the printer's real,
	// catalog-backed configured slots -- never more or fewer than the file
	// actually needs (confirmed via direct testing against a real downloaded
	// multi-color model: sending a mismatched count, e.g. all 4 configured
	// slots for a file that only needs 2, crashes the OrcaSlicer CLI outright
	// rather than failing gracefully).
	const effectiveFilamentProfiles = useMemo(
		() => roleNozzleAssignments.map((slotIdx) => (slotIdx !== null ? (filamentSlots[slotIdx]?.profile ?? '') : '')),
		[roleNozzleAssignments, filamentSlots],
	);

	// Only worth showing when there's an actual choice to make: either the
	// printer has more than one nozzle to pick from, or the file itself
	// needs more than one color (in which case a per-role mapping is
	// mandatory even on a printer with just one configured slot repeated).
	const showNozzleAssignment = filamentSlots.length > 1 || fileRoles.length > 1;
	return { fileRoles, allRolesAssigned, effectiveFilamentProfiles, showNozzleAssignment };
}
