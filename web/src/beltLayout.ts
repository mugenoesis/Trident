import type { ObjectInfo } from './types'

/** How a file on several plates is lined up: plate by plate, or every object in one row. */
export type RowMode = 'plates' | 'objects'

export interface RowShift {
  dx: number
  dy: number
}

/** The kept objects in the order they are laid out: `order` first (kept ones only), then any it left out. */
export function keptInOrder(objects: ObjectInfo[], order: number[], excluded: Set<number>): number[] {
  const kept = objects.filter((o) => !excluded.has(o.index)).map((o) => o.index)
  const wanted = order.filter((i) => kept.includes(i))
  return [...wanted, ...kept.filter((i) => !wanted.includes(i))]
}

/** Plates (by number) in the order they come along the belt: the order their first kept object appears in `final`. */
export function plateSequence(objects: ObjectInfo[], final: number[]): number[] {
  const plateOf = new Map(objects.map((o) => [o.index, o.plate]))
  const plates: number[] = []
  for (const i of final) {
    const plate = plateOf.get(i) ?? 1
    if (!plates.includes(plate)) plates.push(plate)
  }
  return plates
}

/**
 * Where each kept object goes when a belt printer lines a file up (the same rule as the server's
 * threemf_objects.write_derived_3mf): as a move from its place in the file, relative to the first object
 * of the row.
 *
 * Objects on one plate go one after another along the belt (Y) in `order`, centred across it. When the
 * kept objects sit on several plates, each plate is one block that keeps the objects' arrangement
 * within it, and the blocks follow one another, plates in the order their first object appears.
 * `gapMm` is left between neighbours. Excluded objects have no entry.
 */
export function beltRowShifts(
  objects: ObjectInfo[],
  order: number[],
  excluded: Set<number>,
  gapMm: number,
  mode: RowMode = 'plates',
): Record<number, RowShift> {
  const byIndex = new Map(objects.map((o) => [o.index, o]))
  const final = keptInOrder(objects, order, excluded)
  const box = (i: number) => {
    const o = byIndex.get(i) as ObjectInfo
    return { x0: o.center_x_mm - o.width_mm / 2, x1: o.center_x_mm + o.width_mm / 2, y0: o.center_y_mm - o.depth_mm / 2, y1: o.center_y_mm + o.depth_mm / 2 }
  }
  const shifts: Record<number, RowShift> = {}
  const plates = plateSequence(objects, final)
  // One block per plate, or one block per object when everything is on a single plate.
  const blocks: number[][] =
    mode === 'plates' && plates.length > 1 ? plates.map((p) => final.filter((i) => (byIndex.get(i)?.plate ?? 1) === p)) : final.map((i) => [i])
  let cursor = 0
  for (const members of blocks) {
    const boxes = members.map(box)
    const x0 = Math.min(...boxes.map((b) => b.x0))
    const x1 = Math.max(...boxes.map((b) => b.x1))
    const y0 = Math.min(...boxes.map((b) => b.y0))
    const y1 = Math.max(...boxes.map((b) => b.y1))
    for (const i of members) shifts[i] = { dx: -(x0 + x1) / 2, dy: cursor - y0 }
    cursor += y1 - y0 + gapMm
  }
  return shifts
}
