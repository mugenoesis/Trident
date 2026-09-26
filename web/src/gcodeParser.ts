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
 */
export function parseGcode(text: string): ParsedGcode {
  const layers: GcodeLayer[] = []
  let currentLayer: GcodeLayer | null = null

  let x = 0
  let y = 0
  let z = 0
  let e = 0
  let relativeE = false

  for (const rawLine of text.split('\n')) {
    const trimmed = rawLine.trim()
    if (trimmed === ';LAYER_CHANGE' || !currentLayer) {
      currentLayer = { segments: [] }
      layers.push(currentLayer)
      if (trimmed === ';LAYER_CHANGE') continue
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
      const args = parseArgs(parts)
      if (args.has('E')) e = args.get('E')!
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
      currentLayer.segments.push({ x1: x, y1: y, z1: z, x2: nx, y2: ny, z2: nz })
    }

    x = nx
    y = ny
    z = nz
    if (args.has('E')) e = relativeE ? e + eDelta : args.get('E')!
  }

  return { layers: layers.filter((l) => l.segments.length > 0) }
}
