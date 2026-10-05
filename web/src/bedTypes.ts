// Which build plates a material can print on. A filament profile lists a bed
// temperature per plate type; a temperature of 0 means "not for this plate",
// and the slicer refuses the whole job ("Filaments are not compatible with the
// plate type") if the chosen plate has one. A plate the profile does not
// mention at all is left available.
export const PLATE_TEMP_KEYS: [string, string][] = [
  ['textured_plate_temp', 'Textured PEI Plate'],
  ['cool_plate_temp', 'Cool Plate'],
  ['eng_plate_temp', 'Engineering Plate'],
  ['hot_plate_temp', 'High Temp Plate'],
  ['textured_cool_plate_temp', 'Textured Cool Plate'],
  ['supertack_plate_temp', 'Supertack Plate'],
]

function firstNumber(value: unknown): number | null {
  const v = Array.isArray(value) ? value[0] : value
  const n = typeof v === 'string' || typeof v === 'number' ? Number(v) : NaN
  return Number.isFinite(n) ? n : null
}

/**
 * The plates every one of these filament profiles (their resolved `data`)
 * supports, in a stable order, or null when none of them says anything about
 * plates (nothing to restrict).
 */
export function supportedBedTypes(filaments: Record<string, unknown>[]): string[] | null {
  let mentioned = false
  const out: string[] = []
  for (const [key, plate] of PLATE_TEMP_KEYS) {
    const temps = filaments.map((f) => firstNumber(f[key]))
    if (temps.some((t) => t !== null)) mentioned = true
    // Unmentioned (null) counts as supported; an explicit 0 does not.
    if (temps.every((t) => t === null || t > 0)) out.push(plate)
  }
  return mentioned ? out : null
}

/** The plate to use when the current one is not supported: the printer's own
 *  default if the material allows it, else the first supported one. */
export function pickBedType(supported: string[], printerDefault: string | null): string {
  return printerDefault && supported.includes(printerDefault) ? printerDefault : supported[0]
}
