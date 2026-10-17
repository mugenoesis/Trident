// STL files the browser checks build themselves, so they need no fixture file.

// An ASCII STL box, every triangle wound outward.
export function goodCube(size) {
	const v = [];
	for (const z of [0, size]) for (const y of [0, size]) for (const x of [0, size]) v.push([x, y, z]);
	const quads = [
		[0, 2, 3, 1],
		[4, 5, 7, 6],
		[0, 1, 5, 4],
		[2, 6, 7, 3],
		[0, 4, 6, 2],
		[1, 3, 7, 5],
	];
	const lines = ['solid box'];
	for (const [a, b, c, d] of quads) {
		for (const tri of [
			[v[a], v[b], v[c]],
			[v[a], v[c], v[d]],
		]) {
			lines.push('facet normal 0 0 0', 'outer loop', ...tri.map((p) => `vertex ${p[0]} ${p[1]} ${p[2]}`), 'endloop', 'endfacet');
		}
	}
	lines.push('endsolid box');
	return Buffer.from(lines.join('\n'));
}
