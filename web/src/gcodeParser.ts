import { type BeltTransform, beltBackTransformPoint } from './beltTransform';

interface GcodeSegment {
	x1: number;
	y1: number;
	z1: number;
	x2: number;
	y2: number;
	z2: number;
	// From the most recent `;TYPE:` comment (OrcaSlicer emits one per feature
	// section, e.g. "Support material", "Support material interface", "Outer
	// wall") -- true for any support-related feature. Used to color support
	// distinctly from the object itself in GcodeViewer, since the two can
	// otherwise be hard to tell apart at a glance (same color, and on a belt
	// printer a support trunk's base can sit far from the object along the
	// belt-travel axis by design).
	isSupport: boolean;
}

export interface GcodeLayer {
	segments: GcodeSegment[];
	// The layer's own nominal height in mm, straight from its first
	// `;HEIGHT:` comment (right after `;LAYER_CHANGE`/`;Z:`, before any
	// `;TYPE:` feature section -- later `;HEIGHT:` comments belong to a
	// specific feature, e.g. a brim ribbon at a different height, and are
	// ignored). Undefined if the gcode flavor doesn't emit this comment.
	// Authoritative for GcodeViewer's solid-mode box thickness -- needed for a
	// belt printer, where consecutive layers' own average Z (the previous
	// stand-in) is no longer monotonic once each nominal slicing layer maps to
	// a diagonal, not horizontal, plane in the object's upright shape.
	height?: number;
}

export interface ParsedGcode {
	layers: GcodeLayer[];
}

function parseArgs(parts: string[]): Map<string, number> {
	const args = new Map<string, number>();
	for (let i = 1; i < parts.length; i++) {
		const letter = parts[i][0]?.toUpperCase();
		const value = Number.parseFloat(parts[i].slice(1));
		if (letter && !Number.isNaN(value)) args.set(letter, value);
	}
	return args;
}

type Point = { x: number; y: number; z: number };

/**
 * Walks G-code line by line, tracking where the head is, and collects the extruding moves by layer.
 * See parseGcode for what it reads and why.
 */
class GcodeReader {
	readonly layers: GcodeLayer[] = [];
	private currentLayer: GcodeLayer | null = null;
	private x = 0;
	private y = 0;
	private z = 0;
	private e = 0;
	private relativeE = false;
	// Accumulated so `raw + offset` stays the machine's true, continuous
	// physical position across a G92 reset (see reset below) -- without this,
	// a belt printer's start gcode re-zeroing Z partway through (confirmed on
	// a real IdeaFormer IR3 V2 slice: "G92 Z0" once after the prime lines,
	// again right before the first layer) makes every point before vs. after
	// the reset get back-transformed as if they were in the SAME frame when
	// they're not, rendering the prime line and the object visibly offset
	// from each other even though the machine never actually moved between them.
	private offset: Point = { x: 0, y: 0, z: 0 };
	// Sticks across layer boundaries (OrcaSlicer only re-emits ";TYPE:" when
	// the feature actually changes, not at the start of every layer) --
	// resetting it on ";LAYER_CHANGE" would silently misclassify every
	// segment at the start of a layer that continues the previous layer's
	// final feature (e.g. a support trunk spanning several layers) as "not
	// support" until the next explicit ";TYPE:" comment.
	private isSupportType = false;

	private readonly beltTransform: BeltTransform | null | undefined;

	constructor(beltTransform?: BeltTransform | null) {
		this.beltTransform = beltTransform;
	}

	private toRenderSpace(p: Point): Point {
		return this.beltTransform ? beltBackTransformPoint(this.beltTransform, p.x, p.y, p.z) : p;
	}

	private here(): Point {
		return { x: this.x + this.offset.x, y: this.y + this.offset.y, z: this.z + this.offset.z };
	}

	line(rawLine: string): void {
		const trimmed = rawLine.trim();
		// A belt slice appends the new layer's Z value directly onto this
		// marker with no separator (e.g. ";LAYER_CHANGE32.4794", confirmed
		// against a real IdeaFormer IR3 V2 slice) -- an exact-string match here
		// would silently never fire for belt gcode, collapsing the whole file
		// into one giant "layer".
		const isLayerChange = trimmed.startsWith(';LAYER_CHANGE');
		if (isLayerChange || !this.currentLayer) {
			this.currentLayer = { segments: [] };
			this.layers.push(this.currentLayer);
			if (isLayerChange) return;
		}
		if (trimmed.startsWith(';')) {
			this.comment(trimmed, this.currentLayer);
			return;
		}
		const line = trimmed.split(';', 1)[0].trim();
		if (line) this.command(line.split(/\s+/), this.currentLayer);
	}

	private comment(trimmed: string, layer: GcodeLayer): void {
		if (trimmed.startsWith(';HEIGHT:') && layer.height === undefined) {
			const parsed = Number.parseFloat(trimmed.slice(';HEIGHT:'.length));
			if (Number.isFinite(parsed)) layer.height = parsed;
		} else if (trimmed.startsWith(';TYPE:')) {
			this.isSupportType = /support/i.test(trimmed.slice(';TYPE:'.length));
		}
	}

	private command(parts: string[], layer: GcodeLayer): void {
		const cmd = parts[0].toUpperCase();
		if (cmd === 'M83' || cmd === 'M82') this.relativeE = cmd === 'M83';
		else if (cmd === 'G92') this.reset(parseArgs(parts));
		else if (cmd === 'G0' || cmd === 'G1') this.move(parseArgs(parts), layer);
	}

	/**
	 * G92 redefines the CURRENT position without moving the head -- e.g. a
	 * belt printer's start gcode uses "G92 Z0" to zero the belt's own
	 * travel origin. Must update the tracked position the same way E is
	 * already handled, or every subsequent move that omits that axis
	 * (carrying the old position forward) drifts by a constant offset.
	 */
	private reset(args: Map<string, number>): void {
		const newE = args.get('E');
		if (newE !== undefined) this.e = newE;
		for (const axis of ['x', 'y', 'z'] as const) {
			const v = args.get(axis.toUpperCase());
			if (v === undefined) continue;
			this.offset[axis] += this[axis] - v;
			this[axis] = v;
		}
	}

	private move(args: Map<string, number>, layer: GcodeLayer): void {
		const next = { x: args.get('X') ?? this.x, y: args.get('Y') ?? this.y, z: args.get('Z') ?? this.z };
		const newE = args.get('E');
		const eDelta = newE === undefined ? 0 : this.relativeE ? newE : newE - this.e;
		if (eDelta > 0) {
			const p1 = this.toRenderSpace(this.here());
			const p2 = this.toRenderSpace({
				x: next.x + this.offset.x,
				y: next.y + this.offset.y,
				z: next.z + this.offset.z,
			});
			layer.segments.push({ x1: p1.x, y1: p1.y, z1: p1.z, x2: p2.x, y2: p2.y, z2: p2.z, isSupport: this.isSupportType });
		}
		this.x = next.x;
		this.y = next.y;
		this.z = next.z;
		if (newE !== undefined) this.e = this.relativeE ? this.e + eDelta : newE;
	}
}

/**
 * Extracts extruding toolpath segments from G-code text, grouped by layer.
 * Layer boundaries come from OrcaSlicer's own `;LAYER_CHANGE` comment
 * (emitted right before each layer's first move, for every printer this
 * app supports, belt included) rather than "Z changed" -- confirmed
 * against a real IdeaFormer IR3 V2 (belt) slice that Z-based grouping
 * splinters into 541 bogus "layers" for a 9-layer part: a belt printer's
 * gcode Z legitimately steps through more than one distinct value per
 * real layer (small Z moves the belt-shear transform introduces that
 * aren't layer changes at all), which "Z changed" can't tell apart from
 * an actual layer boundary but the slicer's own marker always can.
 * Travel/retraction moves are dropped from the returned segments (this is
 * a print-path preview, not a full simulation, and travel lines mostly
 * just clutter it).
 *
 * Assumes absolute XYZ positioning (G91 relative-mode is essentially never
 * used in sliced FDM output) but handles both absolute (M82, the default)
 * and relative (M83) extrusion, since which one a given profile/gcode
 * flavor uses varies.
 *
 * `beltTransform`, when given, un-shears every point back into the object's
 * upright shape before it's stored (see beltTransform.ts) -- omit/pass null
 * for a non-belt printer, which renders G-code coordinates as-is.
 */
export function parseGcode(text: string, beltTransform?: BeltTransform | null): ParsedGcode {
	const reader = new GcodeReader(beltTransform);
	for (const rawLine of text.split('\n')) reader.line(rawLine);
	return { layers: reader.layers.filter((l) => l.segments.length > 0) };
}
