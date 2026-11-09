import { useCallback, useEffect, useRef, useState } from 'react';
import { previewMixes } from '../api';
import { assignmentsAfterCountChange, assignmentsAfterMixRemoved, mixSlotIndex } from '../mixedColours';
import type { MixedFilament } from '../types';
import type { AppState, MainAppProps } from './useAppState';

// The colour each mix gives, as the server's mixer works it out; the colours of the last answer stay until the next one comes.
export function useMixColours(colours: string[], mixes: MixedFilament[]): string[] {
	const [mixColours, setMixColours] = useState<string[]>([]);
	// One string, so the effect runs when the colours or mixes change, not on every render.
	const request = JSON.stringify([colours, mixes]);
	useEffect(() => {
		const [slotColours, wanted] = JSON.parse(request) as [string[], MixedFilament[]];
		if (wanted.length === 0) return;
		let stale = false;
		const timer = setTimeout(() => {
			previewMixes(slotColours, wanted)
				.then((answer) => {
					if (!stale) setMixColours(answer);
				})
				.catch(() => undefined);
		}, 200);
		return () => {
			stale = true;
			clearTimeout(timer);
		};
	}, [request]);
	return mixes.length === 0 ? [] : mixColours;
}

export function useMixedColours(c: AppState & Pick<MainAppProps, never>) {
	const { filamentSlots, mixes, setMixes, setRoleNozzleAssignments } = c;
	const count = filamentSlots.length;
	const mixColours = useMixColours(
		filamentSlots.map((s) => s.color),
		mixes,
	);

	// A mix names its filaments by slot number and sits right after the last one, so with a different number of filaments the numbers no
	// longer mean what they did: the mixes go, and so does what was assigned to a slot that moved.
	const countBefore = useRef(count);
	useEffect(() => {
		const before = countBefore.current;
		countBefore.current = count;
		if (before === count || mixes.length === 0) return;
		setMixes([]);
		setRoleNozzleAssignments((assignments) => assignmentsAfterCountChange(assignments, before, count));
	}, [count, mixes.length, setMixes, setRoleNozzleAssignments]);

	const addMix = useCallback((mix: MixedFilament) => setMixes((prev) => [...prev, mix]), [setMixes]);
	const updateMix = useCallback(
		(index: number, mix: MixedFilament) => setMixes((prev) => prev.map((m, i) => (i === index ? mix : m))),
		[setMixes],
	);
	const removeMix = useCallback(
		(index: number) => {
			setMixes((prev) => prev.filter((_, i) => i !== index));
			setRoleNozzleAssignments((assignments) => assignmentsAfterMixRemoved(assignments, mixSlotIndex(index, count)));
		},
		[count, setMixes, setRoleNozzleAssignments],
	);
	return { mixColours, addMix, updateMix, removeMix };
}
