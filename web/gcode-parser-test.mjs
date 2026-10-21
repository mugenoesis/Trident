// Unit check of the G-code parser behind the preview (src/gcodeParser.ts): which comments start a layer, give its height and mark a support
// feature, for each way a slicer writes them. It needs no browser and no container: Vite loads the TypeScript, and it runs as
//
//   npm run test:parser
//
import { createServer } from 'vite';

const fail = (message) => {
	throw new Error(message);
};
const check = (condition, message) => {
	if (!condition) fail(message);
	console.log(`   ok: ${message}`);
};

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
const { parseGcode } = await vite.ssrLoadModule('/src/gcodeParser.ts');

// One square of walls per layer, written the way each slicer writes its layer, height and feature comments.
const square = (z) => [`G1 X10 Y10 Z${z} F3000`, 'G1 X20 Y10 E0.5', 'G1 X20 Y20 E0.5', 'G1 X10 Y20 E0.5'];
const gcode = (...lines) => `M83\n${lines.flat().join('\n')}\n`;

console.log('[1/4] OrcaSlicer’s own markers (every printer but a Bambu one) ...');
const orca = parseGcode(
	gcode(
		[';LAYER_CHANGE', ';Z:0.2', ';HEIGHT:0.2', ';TYPE:Outer wall'],
		square(0.2),
		[';LAYER_CHANGE', ';Z:0.4', ';HEIGHT:0.2', ';TYPE:Support material'],
		square(0.4),
	),
);
check(orca.layers.length === 2, 'each ;LAYER_CHANGE starts a layer');
check(orca.layers[0].height === 0.2, 'a layer’s height is read from ;HEIGHT:');
check(orca.layers[0].segments.every((s) => !s.isSupport) && orca.layers[1].segments.every((s) => s.isSupport), ';TYPE: marks support');

console.log('[2/4] A Bambu printer’s G-code (as OrcaSlicer writes it for an A1 mini) ...');
const bambu = parseGcode(
	gcode(
		['; CHANGE_LAYER', '; Z_HEIGHT: 0.2', '; LAYER_HEIGHT: 0.2', '; layer num/total_layer_count: 1/3', '; FEATURE: Outer wall'],
		square(0.2),
		['; CHANGE_LAYER', '; Z_HEIGHT: 0.4', '; LAYER_HEIGHT: 0.2', '; layer num/total_layer_count: 2/3', '; FEATURE: Support'],
		square(0.4),
		['; CHANGE_LAYER', '; Z_HEIGHT: 0.6', '; LAYER_HEIGHT: 0.2', '; layer num/total_layer_count: 3/3', '; FEATURE: Outer wall'],
		square(0.6),
	),
);
check(bambu.layers.length === 3, 'each ; CHANGE_LAYER starts a layer (not one layer for the whole print)');
check(
	bambu.layers.every((l) => l.height === 0.2),
	'a layer’s height is read from ; LAYER_HEIGHT:',
);
check(
	!bambu.layers[0].segments.some((s) => s.isSupport) && bambu.layers[1].segments.every((s) => s.isSupport),
	'; FEATURE: Support marks support, and a wall does not',
);
check(
	bambu.layers[2].segments.every((s) => !s.isSupport),
	'the feature changes back to a wall in the next layer',
);

console.log('[3/4] Bambu Studio’s spelling of the height ...');
const studio = parseGcode(gcode(['; CHANGE_LAYER', '; Z_HEIGHT: 0.28', '; LAST_Z: 0', '; HEIGHT: 0.28'], square(0.28)));
check(studio.layers.length === 1 && studio.layers[0].height === 0.28, '; HEIGHT: gives the height too');

console.log('[4/4] What must not change ...');
const interface_ = parseGcode(gcode([';LAYER_CHANGE', ';HEIGHT:0.2', ';TYPE:Support material interface'], square(0.2)));
check(
	interface_.layers[0].segments.every((s) => s.isSupport),
	'a support interface is support',
);
const brim = parseGcode(gcode(['; CHANGE_LAYER', '; LAYER_HEIGHT: 0.2', '; FEATURE: Brim', '; LAYER_HEIGHT: 0.25'], square(0.2)));
check(brim.layers[0].height === 0.2, 'only the first height of a layer is its own (a later one belongs to a feature)');
const feature = parseGcode(gcode(['; CHANGE_LAYER', '; FEATURE: Support', '; CHANGE_LAYER', '; Z_HEIGHT: 0.4'], square(0.4)));
check(feature.layers.length === 1, 'a layer with no moves is not a layer');
check(parseGcode('').layers.length === 0, 'an empty file has no layers');

await vite.close();
console.log('gcode parser check passed');
