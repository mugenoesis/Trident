/**
 * Undoes a belt printer's machine-frame coordinate transform, recovering the
 * object's true "upright" (as-designed) shape from raw sliced G-code -- the
 * same job vendor/orcaslicer/src/libslic3r/GCode/BeltBackTransform.cpp +
 * GCode/MachineFrameTransform.cpp do for OrcaSlicer's own native preview.
 *
 * Why this is needed: a belt printer's G-code is NOT plain Cartesian
 * (X=lateral, Y=depth, Z=height). OrcaSlicer's belt pipeline is:
 *   upright design -> pre-slice rotation (belt_slice_rotation_angle, mesh-side)
 *                   -> slice normally in the rotated frame
 *                   -> back-transform (undoes the rotation, restores upright)
 *                   -> gcode_remap_x/y/z (permutes upright axes onto gcode letters)
 *                   -> MachineFrameTransform (shear + scale, final machine coords)
 * Everything up through the back-transform step is internal to OrcaSlicer;
 * only the LAST two steps' *inverse* is needed here, since their output is
 * exactly what ends up in the .gcode file's X/Y/Z. Confirmed against a real
 * IdeaFormer IR3 V2 slice's own gcode config dump:
 *   gcode_remap_x=rev_x, gcode_remap_y=pos_z, gcode_remap_z=pos_y,
 *   belt_slice_rotation=x, belt_slice_rotation_angle=45
 * i.e. the file's "Y" letter carries upright height and "Z" carries upright
 * depth, both additionally sheared/scaled by MachineFrameTransform -- plotting
 * raw X/Y/Z (as a non-belt gcode viewer would) renders a confusing, sheared
 * projection instead of the object's recognizable shape.
 */

export type RemapAxisCode = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8

// Matches RemapAxis's C++ declaration order exactly (GCodeWriter.cpp's
// apply_axis_remap: axis = code % 3; code<3 identity, code<6 negate,
// else "reverse against the bed's own max on that axis").
const REMAP_CODE_BY_STRING: Record<string, RemapAxisCode> = {
  pos_x: 0,
  pos_y: 1,
  pos_z: 2,
  neg_x: 3,
  neg_y: 4,
  neg_z: 5,
  rev_x: 6,
  rev_y: 7,
  rev_z: 8,
}

function remapCodeFromString(value: unknown): RemapAxisCode {
  if (typeof value === 'string' && value in REMAP_CODE_BY_STRING) return REMAP_CODE_BY_STRING[value]
  return 0 // PosX -- same fallback GCodeProcessor.cpp's parse_remap_axis uses
}

export interface BeltTransform {
  rotationAxis: 'x' | 'y'
  angleDeg: number
  // One remap code per GCODE letter, in [x, y, z] order -- i.e. remapCodes[0]
  // says where the file's "X" value came from, not the other way around.
  remapCodes: [RemapAxisCode, RemapAxisCode, RemapAxisCode]
  // The bed's own max X/Y (from printable_area) and max Z (printable_height)
  // -- only used by a "rev_*" remap code, which reads as "this axis measured
  // from the bed's far edge".
  boundsMax: [number, number, number]
}

/**
 * Builds a BeltTransform from a machine profile's resolved config (GET
 * /profiles/.../machine/... `data`, now that ProfileCatalog resolves
 * `inherits` chains -- see api/app/profiles.py), or null if this printer
 * isn't a belt printer / has no machine-frame tilt (matches
 * MachineFrameTransform::init_from_config's own gates), in which case
 * callers should render G-code coordinates as-is, same as any normal
 * printer.
 */
export function parseBeltTransform(
  profileData: Record<string, unknown>,
  boundsMax: [number, number, number],
): BeltTransform | null {
  const isBeltPrinter = profileData.belt_printer === '1' || profileData.belt_printer === true
  if (!isBeltPrinter) return null

  const rotationAxisRaw = String(profileData.belt_slice_rotation ?? '').toLowerCase()
  if (rotationAxisRaw !== 'x' && rotationAxisRaw !== 'y') return null // Z/none: no machine-frame tilt

  const decouple = profileData.belt_frame_tilt_decouple === '1' || profileData.belt_frame_tilt_decouple === true
  const angleDeg = Number(
    decouple ? (profileData.belt_frame_tilt_angle ?? 0) : (profileData.belt_slice_rotation_angle ?? 0),
  )
  if (!Number.isFinite(angleDeg) || Math.abs(angleDeg) < 1e-6) return null

  return {
    rotationAxis: rotationAxisRaw,
    angleDeg,
    remapCodes: [
      remapCodeFromString(profileData.gcode_remap_x),
      remapCodeFromString(profileData.gcode_remap_y),
      remapCodeFromString(profileData.gcode_remap_z),
    ],
    boundsMax,
  }
}

/**
 * Inverts GCodeWriter::apply_axis_remap: given the raw gcode-letter values
 * and which upright axis + sign each letter encodes, recovers [upright_x,
 * upright_y, upright_z]. A well-formed remap is a bijection over axis
 * 0/1/2 (each upright axis lands on exactly one gcode letter) -- true for
 * every real machine profile, since otherwise the machine couldn't move
 * correctly on all 3 axes.
 */
function unapplyAxisRemap(
  gcodeXyz: readonly [number, number, number],
  remapCodes: readonly [RemapAxisCode, RemapAxisCode, RemapAxisCode],
  boundsMax: readonly [number, number, number],
): [number, number, number] {
  const upright: [number, number, number] = [0, 0, 0]
  for (let letter = 0; letter < 3; letter++) {
    const code = remapCodes[letter]
    const axis = code % 3
    const value = gcodeXyz[letter]
    if (code < 3) upright[axis] = value
    else if (code < 6) upright[axis] = -value
    else upright[axis] = boundsMax[axis] - value
  }
  return upright
}

/**
 * Applies the belt back-transform to one raw gcode-space point, returning
 * the object's upright coordinates. Pure/stateless -- safe to call per
 * toolpath point.
 */
export function beltBackTransformPoint(
  transform: BeltTransform,
  gx: number,
  gy: number,
  gz: number,
): { x: number; y: number; z: number } {
  const angleRad = (transform.angleDeg * Math.PI) / 180
  const sinA = Math.sin(angleRad)
  const cosA = Math.cos(angleRad)

  // Undo MachineFrameTransform's shear+scale first (it runs AFTER the axis
  // remap, so its inverse must run BEFORE undoing the remap here) -- see
  // MachineFrameTransform.cpp's init_from_config: for angle a on rotation
  // axis X, forward is (x,y,z) -> (x, y/sin(a), z + y*cot(a)); axis Y is the
  // same mapping on X/Z with the opposite shear sign. Both simplify (cot(a) =
  // cos(a)/sin(a) cancels the sin(a) from un-scaling) to a plain sin/cos
  // correction using the ORIGINAL sheared value, no intermediate needed.
  let preShear: [number, number, number] = [gx, gy, gz]
  if (Math.abs(sinA) > 1e-9) {
    if (transform.rotationAxis === 'x') {
      preShear = [gx, gy * sinA, gz - gy * cosA]
    } else {
      preShear = [gx * sinA, gy, gz + gx * cosA]
    }
  }

  const [ux, uy, uz] = unapplyAxisRemap(preShear, transform.remapCodes, transform.boundsMax)
  return { x: ux, y: uy, z: uz }
}
