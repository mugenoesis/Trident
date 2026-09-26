import * as THREE from 'three'
import { STLExporter } from 'three/examples/jsm/exporters/STLExporter.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { parseBeltTransform, type BeltTransform } from './beltTransform'

export interface Dimensions {
  x: number
  y: number
  z: number
}

export interface BedSize {
  width: number // X, mm
  depth: number // Y, mm
  height: number // Z (printable_height), mm
  // True for a belt printer's own (deliberately very long) bed, where Y
  // represents distance traveled along the belt rather than a normal
  // bounded dimension -- see `belt_printer_infinite_y` in the machine
  // profile. Drives the Viewer's default object placement below instead of
  // the usual dead-plate-center placement.
  beltPrinterInfiniteY: boolean
  // Non-null only for an actual belt printer with a real machine-frame tilt
  // (belt_printer + belt_slice_rotation != none/z) -- see beltTransform.ts.
  // GcodeViewer uses this to un-shear raw G-code coordinates back into the
  // object's upright shape; null means "render G-code as-is", same as any
  // normal printer.
  beltTransform: BeltTransform | null
}

// A margin below 1.0: an exact-fit scale can still fail slicer validation
// for sitting flush against the bed edge, and it looks uncomfortably tight
// in the viewer.
const FIT_MARGIN = 0.97

// How far from the belt's own Y origin (the end where the prime lines /
// purge blob live, see machine_start_gcode) a belt printer's slicer engine
// places a fresh object by default -- vendor/orcaslicer/src/OrcaSlicer.cpp's
// `center_instances_around_point` recenter uses this exact same 15mm
// margin (deliberately small: confirmed via the gcode viewer's belt
// back-transform that a larger margin leaves the object not actually
// touching the prime lines, defeating their first-layer-adhesion purpose).
// Kept in sync manually since the preview re-derives this position on the
// client rather than asking the slicer for it.
export const BELT_PRINTER_PREVIEW_MARGIN_MM = 15

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
  const maxX = Math.max(...xs)
  const maxY = Math.max(...ys)
  const width = maxX - Math.min(...xs)
  const depth = maxY - Math.min(...ys)
  const height = Number(heightRaw)

  if (!(width > 0) || !(depth > 0) || !Number.isFinite(height) || !(height > 0)) return null

  const beltFlag = profileData.belt_printer_infinite_y
  const beltPrinterInfiniteY = beltFlag === '1' || beltFlag === true || beltFlag === 1
  // set_build_volume_max (GCode.cpp) uses the bed polygon's own max X/Y plus
  // printable_height -- matched here so a "rev_*" gcode_remap axis inverts
  // against the same reference the slicer itself used.
  const beltTransform = parseBeltTransform(profileData, [maxX, maxY, height])

  return { width, depth, height, beltPrinterInfiniteY, beltTransform }
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
 * Re-parses `file` and scales the mesh by `factors` (pass the same value
 * three times for uniform scaling), returning a new STL File (binary, same
 * filename) -- not just a visual scale on the preview. Used so the model
 * actually slices at the scaled size instead of only *looking* different in
 * the viewer.
 */
export async function scaleStlFile(file: File, factors: Dimensions): Promise<File> {
  const buffer = await file.arrayBuffer()
  const geometry = new STLLoader().parse(buffer)
  geometry.scale(factors.x, factors.y, factors.z)
  const mesh = new THREE.Mesh(geometry)
  const output = new STLExporter().parse(mesh, { binary: true }) as unknown as DataView
  // TS's BlobPart type requires .buffer to be exactly ArrayBuffer, not the
  // wider ArrayBufferLike DataView/TypedArray carry (in case they wrap a
  // SharedArrayBuffer) -- STLExporter always allocates a plain
  // `new ArrayBuffer(...)`, so this is safe at runtime.
  const bytes = new Uint8Array(output.buffer, output.byteOffset, output.byteLength)
  return new File([bytes as unknown as BlobPart], file.name, { type: 'model/stl' })
}
