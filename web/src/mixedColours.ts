import type { MixedFilament } from './types';

// The pure logic of the Mixed colours panel. A mixed colour is a slot that is not loaded in any nozzle: the slicer prints it as 2 or 3 of
// the physical filaments, layer by layer. Mixed slots come after the physical ones, so with 4 filaments the first mix is slot index 4.

// How many filaments one mix can be made of (the slicer's own limit).
export const MAX_MIX_COMPONENTS = 3;

// The colour shown for a mix until the server has worked it out.
const UNKNOWN_COLOUR = '#808080';

// A share is a weight on a slider; it starts even.
const START_WEIGHT = 50;

interface SlotLike {
	profile: string;
	color: string;
}

const totalOf = (weights: number[]): number => weights.reduce((a, b) => a + b, 0);

// "Blue 50% + Yellow 50%": each filament's share of the total, by its name.
export function recipeText(mix: MixedFilament, names: string[]): string {
	const total = totalOf(mix.weights);
	return mix.components.map((slot, i) => `${names[slot - 1]} ${Math.round((mix.weights[i] / total) * 100)}%`).join(' + ');
}

// A plain word for a CIE76 colour difference from the wanted colour.
export function closenessLabel(distance: number): string {
	if (distance < 2) return 'looks the same';
	if (distance < 6) return 'very close';
	if (distance < 12) return 'close';
	return 'only roughly';
}

export function isComplete(mix: MixedFilament): boolean {
	return mix.components.length >= 2;
}

// Picks a filament for the mix, or takes it out when it is already in. A fourth is refused.
export function toggleComponent(mix: MixedFilament, slot: number): MixedFilament {
	const at = mix.components.indexOf(slot);
	if (at >= 0) {
		return { components: mix.components.filter((_, i) => i !== at), weights: mix.weights.filter((_, i) => i !== at) };
	}
	if (mix.components.length >= MAX_MIX_COMPONENTS) return mix;
	return { components: [...mix.components, slot], weights: [...mix.weights, START_WEIGHT] };
}

export function setWeight(mix: MixedFilament, index: number, weight: number): MixedFilament {
	return { ...mix, weights: mix.weights.map((w, i) => (i === index ? weight : w)) };
}

// The colours of the layers a mix prints, bottom to top: whole layers take turns by share (the slicer's own deficit round-robin).
export function layerColours(mix: MixedFilament, colours: string[], layers = 10): string[] {
	const total = totalOf(mix.weights);
	const owed = mix.weights.map(() => 0);
	const printed: string[] = [];
	for (let layer = 0; layer < layers; layer++) {
		for (let i = 0; i < owed.length; i++) owed[i] += mix.weights[i] / total;
		const pick = owed.indexOf(Math.max(...owed));
		owed[pick] -= 1;
		printed.push(colours[mix.components[pick] - 1]);
	}
	return printed;
}

// The slot index of the mix at `mixIndex` when there are `physicalCount` filaments.
export function mixSlotIndex(mixIndex: number, physicalCount: number): number {
	return physicalCount + mixIndex;
}

// The material a slot is sliced with: a physical slot's own, a mix's is its first filament's (the slicer wants a profile for every slot).
export function slotProfile(index: number, slots: SlotLike[], mixes: MixedFilament[]): string {
	if (index < slots.length) return slots[index]?.profile ?? '';
	const first = mixes[index - slots.length]?.components[0];
	return first === undefined ? '' : (slots[first - 1]?.profile ?? '');
}

// The colour a slot shows in the preview: a mix has the colour the server worked out for it.
export function slotColour(index: number, slots: SlotLike[], mixes: MixedFilament[], mixColours: string[]): string {
	if (index < slots.length) return slots[index]?.color ?? UNKNOWN_COLOUR;
	return mixes[index - slots.length] ? (mixColours[index - slots.length] ?? UNKNOWN_COLOUR) : UNKNOWN_COLOUR;
}

// When the number of physical filaments changes, a mixed slot is no longer at the index it was: what was assigned to one is let go
// (along with a filament that no longer exists).
export function assignmentsAfterCountChange(assignments: (number | null)[], before: number, after: number): (number | null)[] {
	const firstGone = Math.min(before, after);
	return assignments.map((slot) => (slot !== null && slot >= firstGone ? null : slot));
}

// A mix is removed: what was assigned to it is let go, and the mixes after it each move up one slot.
export function assignmentsAfterMixRemoved(assignments: (number | null)[], removedSlot: number): (number | null)[] {
	return assignments.map((slot) => {
		if (slot === null || slot < removedSlot) return slot;
		return slot === removedSlot ? null : slot - 1;
	});
}

// What a slice request depends on in the mixes, for the "already sliced with these settings" check: the sub-layer choice only counts with a mix.
export function mixSignatureOf(mixes: MixedFilament[], sublayers: boolean): string {
	return JSON.stringify(mixes.length > 0 ? [mixes, sublayers] : []);
}
