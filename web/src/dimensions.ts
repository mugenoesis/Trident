import * as THREE from 'three'
import { STLExporter } from 'three/examples/jsm/exporters/STLExporter.js'
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js'
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
  // Where the bed's front-left corner sits in plate coordinates (almost
  // always 0, 0) -- positions sent to / read from the server are in that frame.
  minX: number
  minY: number
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
// arrange-cap and `center_instances_around_point` recenter both use this
// exact same 15mm margin, close enough that the object actually touches the
// prime lines (confirmed: this is what a real belt slice with no support
// enabled lands at). Kept in sync manually since the preview re-derives this
// position on the client rather than asking the slicer for it.
export const BELT_PRINTER_PREVIEW_MARGIN_MM = 15
// Used instead of the above whenever support material is enabled: support
// (a slicing-time computation, after the object's own placement is decided)
// can extend further toward the belt origin than the bare mesh does --
// confirmed on a real belt slice with supports enabled overshooting a 15mm
// placement by ~11.6mm, past the belt's own origin. 30mm leaves roughly 2x
// that overshoot as headroom. Conditioned on enable_support specifically
// (matching OrcaSlicer.cpp) rather than applied unconditionally, since a
// flat 30mm regressed adhesion for every non-support slice -- confirmed the
// object/brim no longer visibly reached the prime lines once it applied
// regardless of settings.
export const BELT_PRINTER_PREVIEW_MARGIN_MM_WITH_SUPPORT = 30

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
  const minX = Math.min(...xs)
  const minY = Math.min(...ys)
  const width = maxX - minX
  const depth = maxY - minY
  const height = Number(heightRaw)

  if (!(width > 0) || !(depth > 0) || !Number.isFinite(height) || !(height > 0)) return null

  const beltFlag = profileData.belt_printer_infinite_y
  const beltPrinterInfiniteY = beltFlag === '1' || beltFlag === true || beltFlag === 1
  // set_build_volume_max (GCode.cpp) uses the bed polygon's own max X/Y plus
  // printable_height -- matched here so a "rev_*" gcode_remap axis inverts
  // against the same reference the slicer itself used.
  const beltTransform = parseBeltTransform(profileData, [maxX, maxY, height])

  return { width, depth, height, minX, minY, beltPrinterInfiniteY, beltTransform }
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
 * Models the browser can re-export as an STL after scaling: STL files and the bundled
 * Draco (.drc) samples. A 3MF carries plates, colours and settings, and a STEP file is
 * CAD geometry; flattening either to an STL would lose that, so they are not scaled here.
 */
export function canScaleFile(file: File): boolean {
  return /\.(stl|drc)$/i.test(file.name)
}

export const SCALE_UNSUPPORTED_MESSAGE =
  'Scaling is available for STL models and the bundled samples. A 3MF or STEP file would lose its plates, colours or CAD data if converted, so scale it in your modelling tool.'

/**
 * Re-parses `file` and scales the mesh by `factors` (pass the same value
 * three times for uniform scaling), returning a new binary STL File -- not just a
 * visual scale on the preview. Used so the model actually slices at the scaled size
 * instead of only *looking* different in the viewer.
 *
 * Reads STL and Draco (.drc, the bundled samples). The result is always an STL,
 * so the file name's extension is replaced: the server picks the format from it.
 */
export async function scaleStlFile(file: File, factors: Dimensions): Promise<File> {
  const lower = file.name.toLowerCase()
  let object: THREE.Object3D
  if (lower.endsWith('.stl')) {
    object = new THREE.Mesh(new STLLoader().parse(await file.arrayBuffer()))
  } else if (lower.endsWith('.drc')) {
    const buffer = await file.arrayBuffer()
    const loader = new DRACOLoader()
    try {
      const geometry = await new Promise<THREE.BufferGeometry>((resolve, reject) => {
        loader.parse(buffer, resolve, reject)
      })
      object = new THREE.Mesh(geometry)
    } finally {
      loader.dispose()
    }
  } else {
    throw new Error(SCALE_UNSUPPORTED_MESSAGE)
  }
  object.scale.set(factors.x, factors.y, factors.z)
  object.updateMatrixWorld(true)
  const output = new STLExporter().parse(object, { binary: true }) as unknown as DataView
  // TS's BlobPart type requires .buffer to be exactly ArrayBuffer, not the
  // wider ArrayBufferLike DataView/TypedArray carry (in case they wrap a
  // SharedArrayBuffer) -- STLExporter always allocates a plain
  // `new ArrayBuffer(...)`, so this is safe at runtime.
  const bytes = new Uint8Array(output.buffer, output.byteOffset, output.byteLength)
  const stem = file.name.replace(/\.[^.]*$/, '') || 'model'
  return new File([bytes as unknown as BlobPart], stem + '.stl', { type: 'model/stl' })
}

// Where the slicer puts a lone model when nothing is chosen (plate
// coordinates of its footprint centre): the middle of the bed, or on a belt
// printer near the prime lines.
export function defaultPlacement(bed: BedSize, supportEnabled: boolean): { x: number; y: number } {
  const x = bed.minX + bed.width / 2
  if (bed.beltPrinterInfiniteY) {
    const margin = supportEnabled ? BELT_PRINTER_PREVIEW_MARGIN_MM_WITH_SUPPORT : BELT_PRINTER_PREVIEW_MARGIN_MM
    return { x, y: bed.minY + margin }
  }
  return { x, y: bed.minY + bed.depth / 2 }
}

