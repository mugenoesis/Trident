import * as THREE from 'three'
import { STLExporter } from 'three/examples/jsm/exporters/STLExporter.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'

export interface Dimensions {
  x: number
  y: number
  z: number
}

export interface BedSize {
  width: number // X, mm
  depth: number // Y, mm
  height: number // Z (printable_height), mm
}

// A margin below 1.0: an exact-fit scale can still fail slicer validation
// for sitting flush against the bed edge, and it looks uncomfortably tight
// in the viewer.
const FIT_MARGIN = 0.97

/**
 * Printer machine profiles carry their bed as `printable_area` (a polygon of
 * "XxY" corner strings, e.g. ["0x0", "207x0", "207x255", "0x255"]) and
 * `printable_height` (a plain number string) -- see GET /profiles/{vendor}/
 * machine/{name}. This takes the axis-aligned bounding box of the polygon,
 * which is exact for the common rectangular-bed case and a reasonable
 * (slightly generous) approximation for anything else -- fine for a rough
 * "will this roughly fit" check, not a substitute for the slicer's own
 * placement/arrangement logic.
 */
export function parseBedSize(profileData: Record<string, unknown>): BedSize | null {
  const area = profileData.printable_area
  const heightRaw = profileData.printable_height
  if (!Array.isArray(area)) return null

  const points = area
    .filter((p): p is string => typeof p === 'string')
    .map((p) => p.split('x').map(Number))
    .filter((p) => p.length === 2 && p.every((n) => Number.isFinite(n)))
  if (points.length === 0) return null

  const xs = points.map((p) => p[0])
  const ys = points.map((p) => p[1])
  const width = Math.max(...xs) - Math.min(...xs)
  const depth = Math.max(...ys) - Math.min(...ys)
  const height = Number(heightRaw)

  if (!(width > 0) || !(depth > 0) || !Number.isFinite(height) || !(height > 0)) return null
  return { width, depth, height }
}

/**
 * Uniform scale factor needed to fit `model` inside `bed`, or null if it
 * already fits. Doesn't try rotating the model to find a better fit (e.g.
 * swapping X/Y) -- a simple axis-aligned check, matching the model's
 * current orientation as uploaded.
 */
export function computeFitScale(model: Dimensions, bed: BedSize): number | null {
  const ratios = [bed.width / model.x, bed.depth / model.y, bed.height / model.z]
  const minRatio = Math.min(...ratios)
  return minRatio < 1 ? minRatio * FIT_MARGIN : null
}

/**
 * Re-parses `file` and uniformly scales the mesh by `factor`, returning a
 * new STL File (binary, same filename) -- not just a visual scale on the
 * preview. Used so the model actually slices at the scaled size instead of
 * only *looking* smaller in the viewer.
 */
export async function scaleStlFile(file: File, factor: number): Promise<File> {
  const buffer = await file.arrayBuffer()
  const geometry = new STLLoader().parse(buffer)
  geometry.scale(factor, factor, factor)
  const mesh = new THREE.Mesh(geometry)
  const output = new STLExporter().parse(mesh, { binary: true }) as unknown as DataView
  // TS's BlobPart type requires .buffer to be exactly ArrayBuffer, not the
  // wider ArrayBufferLike DataView/TypedArray carry (in case they wrap a
  // SharedArrayBuffer) -- STLExporter always allocates a plain
  // `new ArrayBuffer(...)`, so this is safe at runtime.
  const bytes = new Uint8Array(output.buffer, output.byteOffset, output.byteLength)
  return new File([bytes as unknown as BlobPart], file.name, { type: 'model/stl' })
}
