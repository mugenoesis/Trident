import { beltBackTransformPoint, type BeltTransform } from './beltTransform'

export interface GcodeSegment {
  x1: number
  y1: number
  z1: number
  x2: number
  y2: number
  z2: number
}

export interface GcodeLayer {
  segments: GcodeSegment[]
  // The layer's own nominal height in mm, straight from its first
  // `;HEIGHT:` comment (right after `;LAYER_CHANGE`/`;Z:`, before any
  // `;TYPE:` feature section -- later `;HEIGHT:` comments belong to a
  // specific feature, e.g. a brim ribbon at a different height, and are
  // ignored). Undefined if the gcode flavor doesn't emit this comment.
  // Authoritative for GcodeViewer's solid-mode box thickness -- needed for a
  // belt printer, where consecutive layers' own average Z (the previous
  // stand-in) is no longer monotonic once each nominal slicing layer maps to
  // a diagonal, not horizontal, plane in the object's upright shape.
  height?: number
}

export interface ParsedGcode {
  layers: GcodeLayer[]
}

function parseArgs(parts: string[]): Map<string, number> {
  const args = new Map<string, number>()
  for (let i = 1; i < parts.length; i++) {
    const letter = parts[i][0]?.toUpperCase()
    const value = Number.parseFloat(parts[i].slice(1))
    if (letter && !Number.isNaN(value)) args.set(letter, value)
  }
  return args
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
  const layers: GcodeLayer[] = []
  let currentLayer: GcodeLayer | null = null

  let x = 0
  let y = 0
  let z = 0
  let e = 0
  let relativeE = false

  const toRenderSpace = (px: number, py: number, pz: number) =>
    beltTransform ? beltBackTransformPoint(beltTransform, px, py, pz) : { x: px, y: py, z: pz }

  for (const rawLine of text.split('\n')) {
    const trimmed = rawLine.trim()
    // A belt slice appends the new layer's Z value directly onto this
    // marker with no separator (e.g. ";LAYER_CHANGE32.4794", confirmed
    // against a real IdeaFormer IR3 V2 slice) -- an exact-string match here
    // would silently never fire for belt gcode, collapsing the whole file
    // into one giant "layer".
    const isLayerChange = trimmed.startsWith(';LAYER_CHANGE')
    if (isLayerChange || !currentLayer) {
      currentLayer = { segments: [] }
      layers.push(currentLayer)
      if (isLayerChange) continue
    }

    if (trimmed.startsWith(';HEIGHT:') && currentLayer.height === undefined) {
      const parsed = Number.parseFloat(trimmed.slice(';HEIGHT:'.length))
      if (Number.isFinite(parsed)) currentLayer.height = parsed
      continue
    }

    const line = trimmed.split(';', 1)[0].trim()
    if (!line) continue
    const parts = line.split(/\s+/)
    const cmd = parts[0].toUpperCase()

    if (cmd === 'M83') {
      relativeE = true
      continue
    }
    if (cmd === 'M82') {
      relativeE = false
      continue
    }
    if (cmd === 'G92') {
      // Redefines the CURRENT position without moving the head -- e.g. a
      // belt printer's start gcode uses "G92 Z0" to zero the belt's own
      // travel origin. Must update the tracked position the same way E is
      // already handled below, or every subsequent move that omits that
      // axis (carrying the old position forward) drifts by a constant
      // offset.
      const args = parseArgs(parts)
      if (args.has('E')) e = args.get('E')!
      if (args.has('X')) x = args.get('X')!
      if (args.has('Y')) y = args.get('Y')!
      if (args.has('Z')) z = args.get('Z')!
      continue
    }
    if (cmd !== 'G0' && cmd !== 'G1') continue

    const args = parseArgs(parts)
    const nx = args.has('X') ? args.get('X')! : x
    const ny = args.has('Y') ? args.get('Y')! : y
    const nz = args.has('Z') ? args.get('Z')! : z
    const eDelta = args.has('E') ? (relativeE ? args.get('E')! : args.get('E')! - e) : 0
    const extruding = eDelta > 0

    if (extruding) {
      const p1 = toRenderSpace(x, y, z)
      const p2 = toRenderSpace(nx, ny, nz)
      currentLayer.segments.push({ x1: p1.x, y1: p1.y, z1: p1.z, x2: p2.x, y2: p2.y, z2: p2.z })
    }

    x = nx
    y = ny
    z = nz
    if (args.has('E')) e = relativeE ? e + eDelta : args.get('E')!
  }

  return { layers: layers.filter((l) => l.segments.length > 0) }
}
