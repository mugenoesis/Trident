// Unit check of the pure logic behind the Mixed colours panel (src/mixedColours.ts): the wording of a recipe, picking and weighting the
// filaments of a mix, which layers a mix prints, and what a slot number means once mixed slots follow the physical ones. It needs no
// browser and no container: Vite loads the TypeScript, and it runs as
//
//   npm run test:mixing
//
import { createServer } from 'vite';

const fail = (message) => {
	throw new Error(message);
};
const check = (condition, message) => {
	if (!condition) fail(message);
	console.log(`   ok: ${message}`);
};
const same = (got, want, message) => check(JSON.stringify(got) === JSON.stringify(want), `${message} (${JSON.stringify(got)})`);

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
const m = await vite.ssrLoadModule('/src/mixedColours.ts');

const names = ['White', 'Red', 'Blue', 'Yellow'];
const slots = [
	{ profile: 'PLA A', color: '#ffffff' },
	{ profile: 'PLA B', color: '#e0301e' },
	{ profile: 'PLA C', color: '#0a84ff' },
	{ profile: 'PLA D', color: '#ffd60a' },
];

console.log('[1/7] A recipe in words ...');
same(m.recipeText({ components: [3, 4], weights: [50, 50] }, names), 'Blue 50% + Yellow 50%', 'two filaments, shares of the total');
same(
	m.recipeText({ components: [1, 2, 4], weights: [1, 1, 2] }, names),
	'White 25% + Red 25% + Yellow 50%',
	'three filaments, weights that do not add up to 100',
);

console.log('[2/7] How close a mix is to the wanted colour ...');
same([0.5, 3, 8, 20].map(m.closenessLabel), ['looks the same', 'very close', 'close', 'only roughly'], 'four steps by colour difference');
same(
	[1.99, 2, 5.99, 6, 11.99, 12].map(m.closenessLabel),
	['looks the same', 'very close', 'very close', 'close', 'close', 'only roughly'],
	'each step starts exactly at its limit',
);

console.log('[3/7] Picking the filaments of a mix ...');
let mix = { components: [], weights: [] };
check(!m.isComplete(mix), 'no filament is not a mix');
mix = m.toggleComponent(mix, 3);
check(!m.isComplete(mix), 'one filament is not a mix');
mix = m.toggleComponent(mix, 4);
same(mix, { components: [3, 4], weights: [50, 50] }, 'a picked filament starts at an even share');
check(m.isComplete(mix), 'two filaments make a mix');
mix = m.toggleComponent(mix, 1);
same(mix.components, [3, 4, 1], 'a third filament is added');
same(m.toggleComponent(mix, 2).components, [3, 4, 1], 'a fourth is refused');
same(m.toggleComponent(mix, 4), { components: [3, 1], weights: [50, 50] }, 'picking one again takes it out with its weight');
same(m.setWeight({ components: [3, 4], weights: [50, 50] }, 1, 80).weights, [50, 80], 'a weight is set for one filament only');

console.log('[4/7] The layers a mix prints, bottom to top ...');
const colours = slots.map((s) => s.color);
const stripe = m.layerColours({ components: [3, 4], weights: [50, 50] }, colours, 4);
same(stripe.slice().sort(), ['#0a84ff', '#0a84ff', '#ffd60a', '#ffd60a'], 'an even mix gives each filament half the layers');
check(stripe[0] !== stripe[1], 'and they alternate');
const lopsided = m.layerColours({ components: [3, 4], weights: [75, 25] }, colours, 8);
check(lopsided.filter((c) => c === '#0a84ff').length === 6, 'three quarters of the layers for a 75% share');

console.log('[5/7] What a slot number means (mixed slots follow the physical ones) ...');
const mixes = [
	{ components: [3, 4], weights: [1, 1] },
	{ components: [2, 1], weights: [1, 1] },
];
same(m.slotProfile(1, slots, mixes), 'PLA B', 'a physical slot has its own material');
same(m.slotProfile(4, slots, mixes), 'PLA C', 'the first mix is sliced with its first filament’s material');
same(m.slotProfile(5, slots, mixes), 'PLA B', 'the second mix likewise');
same(m.slotProfile(6, slots, mixes), '', 'a slot that is not there has none');
same(m.slotColour(0, slots, mixes, ['#5BC94D', '#aa5500']), '#ffffff', 'a physical slot shows its colour');
same(m.slotColour(5, slots, mixes, ['#5BC94D', '#aa5500']), '#aa5500', 'a mix shows its mixed colour');
same(m.slotColour(4, slots, mixes, []), '#808080', 'and grey until that colour is known');
same(m.mixSlotIndex(1, 4), 5, 'the second mix of four filaments is slot index 5');

console.log('[6/7] Slot numbers move when filaments or mixes come and go ...');
same(
	m.assignmentsAfterCountChange([0, 4, 5, null, 2], 4, 3),
	[0, null, null, null, 2],
	'index 3 and up go (a filament left, or mixes cleared)',
);
same(m.assignmentsAfterCountChange([0, 4], 4, 5), [0, null], 'a filament added: a mix slot is no longer where it was');
same(
	m.assignmentsAfterMixRemoved([0, 4, 5, 6, null], 5),
	[0, 4, null, 5, null],
	'a removed mix is let go and the mixes after it move up one',
);
same(m.assignmentsAfterMixRemoved([4, 5], 6), [4, 5], 'a mix that was not assigned changes nothing');

console.log('[7/7] What the slice request carries ...');
const { jobRequestOf } = await vite.ssrLoadModule('/src/sliceRequest.ts');
const inputs = {
	modelId: 'm1',
	printerName: 'P',
	processName: 'Q',
	previewImageBase64: undefined,
	filamentProfiles: ['PLA A'],
	overrides: {},
	plateIndex: null,
	placement: null,
	copies: 1,
	excludedObjects: undefined,
	beltLayout: undefined,
};
const plain = jobRequestOf({ ...inputs, mixes: [], mixSublayers: true });
check(!('mixed_filaments' in JSON.parse(JSON.stringify(plain))), 'no mixes: nothing about mixes is sent, not even the sub-layer choice');
check(!('mixed_sublayers' in JSON.parse(JSON.stringify(plain))), 'and no sub-layer flag');
const withMix = jobRequestOf({ ...inputs, mixes, mixSublayers: false });
same(withMix.mixed_filaments, mixes, 'the mixes go as they are');
check(withMix.mixed_sublayers === false, 'with the sub-layer choice');
check(jobRequestOf({ ...inputs, mixes, mixSublayers: true }).mixed_sublayers === true, 'on when it is on');

await vite.close();
console.log('All mixed colour checks passed.');
