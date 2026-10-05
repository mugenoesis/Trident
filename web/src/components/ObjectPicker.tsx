import { useEffect, useMemo, useRef, useState } from 'react'
import { keptInOrder, plateSequence } from '../beltLayout'
import type { ObjectInfo } from '../types'

interface ObjectPickerProps {
  objects: ObjectInfo[]
  // One rendered picture per object index (Viewer's onObjectThumbnails);
  // missing entries fall back to a placeholder.
  thumbnails: Record<number, string>
  excluded: Set<number>
  onExcludedChange: (excluded: Set<number>) => void
  // Belt printers only: line the objects up along the belt, in `order`.
  isBelt: boolean
  lineUp: boolean
  onLineUpChange: (lineUp: boolean) => void
  // Every object index, in print order (excluded ones keep their place so
  // re-including one puts it back where it was).
  order: number[]
  onOrderChange: (order: number[]) => void
  gapMm: number
  onGapChange: (gapMm: number) => void
  // Plate names by plate number, for the plate order of a multi-plate file on a belt printer.
  plateNames?: Record<number, string>
  onClose: () => void
}

const GAP_CHOICES = [5, 10, 20, 50]

// Full-screen picker for which objects of an uploaded file to print, plus
// (belt printers) how they are laid out along the belt.
export default function ObjectPicker({
  objects,
  thumbnails,
  excluded,
  onExcludedChange,
  isBelt,
  lineUp,
  onLineUpChange,
  order,
  onOrderChange,
  gapMm,
  onGapChange,
  plateNames,
  onClose,
}: ObjectPickerProps) {
  const plates = useMemo(() => [...new Set(objects.map((o) => o.plate))].sort((a, b) => a - b), [objects])
  const [plateFilter, setPlateFilter] = useState<number | null>(null)
  const byIndex = useMemo(() => new Map(objects.map((o) => [o.index, o])), [objects])
  const shown = plateFilter === null ? objects : objects.filter((o) => o.plate === plateFilter)
  const selectedCount = objects.length - excluded.size
  // A multi-plate file on a belt printer goes along the belt plate by plate: the order is the plates', not the objects'.
  const finalOrder = useMemo(() => keptInOrder(objects, order, excluded), [objects, order, excluded])
  const rowPlates = useMemo(() => plateSequence(objects, finalOrder), [objects, finalOrder])
  const onePerPlate = rowPlates.length > 1
  const movePlate = (plate: number, by: -1 | 1) => {
    const at = rowPlates.indexOf(plate)
    const to = at + by
    if (at < 0 || to < 0 || to >= rowPlates.length) return
    const next = [...rowPlates]
    next.splice(at, 1)
    next.splice(to, 0, plate)
    const plateOf = (i: number) => byIndex.get(i)?.plate ?? 1
    const lined = next.flatMap((p) => finalOrder.filter((i) => plateOf(i) === p))
    onOrderChange([...lined, ...order.filter((i) => !lined.includes(i))])
  }

  const toggle = (index: number) => {
    const next = new Set(excluded)
    if (next.has(index)) next.delete(index)
    else next.add(index)
    onExcludedChange(next)
  }
  const setAll = (include: boolean) => {
    const next = new Set(excluded)
    for (const o of shown) {
      if (include) next.delete(o.index)
      else next.add(o.index)
    }
    onExcludedChange(next)
  }

  return (
    <div className="object-picker" role="dialog" aria-modal="true" aria-label="Objects to print">
      <div className="object-picker-header">
        <strong>Objects</strong>
        <button type="button" className="link-button" onClick={onClose}>
          Close ✕
        </button>
      </div>

      {plates.length > 1 && (
        <div className="object-picker-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={plateFilter === null}
            className={`object-picker-tab${plateFilter === null ? ' active' : ''}`}
            onClick={() => setPlateFilter(null)}
          >
            All
          </button>
          {plates.map((p) => (
            <button
              type="button"
              role="tab"
              key={p}
              aria-selected={plateFilter === p}
              className={`object-picker-tab${plateFilter === p ? ' active' : ''}`}
              onClick={() => setPlateFilter(p)}
            >
              Plate {p}
            </button>
          ))}
        </div>
      )}

      <div className="object-picker-scroll">
        <div className="object-picker-grid">
          {shown.map((o) => {
            const off = excluded.has(o.index)
            return (
              <button
                type="button"
                key={o.index}
                className={`object-tile${off ? ' off' : ''}`}
                aria-pressed={!off}
                title={o.name}
                onClick={() => toggle(o.index)}
              >
                <span className={`object-tile-check${off ? '' : ' on'}`}>{off ? '' : '✓'}</span>
                {thumbnails[o.index] ? (
                  <img className="object-tile-thumb" src={thumbnails[o.index]} alt="" />
                ) : (
                  <span className="object-tile-thumb placeholder">{o.index + 1}</span>
                )}
                <span className="object-tile-name">{o.name}</span>
                <span className="object-tile-size">
                  {Math.round(o.width_mm)}×{Math.round(o.depth_mm)}×{Math.round(o.height_mm)} mm
                </span>
              </button>
            )
          })}
        </div>

        {isBelt && (
          <div className="object-picker-belt">
            <label className="object-picker-row">
              <span>Line objects up along the belt</span>
              <input
                type="checkbox"
                role="switch"
                checked={lineUp}
                onChange={(e) => onLineUpChange(e.target.checked)}
              />
            </label>
            {lineUp && (
              <>
                <label className="object-picker-row">
                  <span>Gap between objects</span>
                  <select value={gapMm} onChange={(e) => onGapChange(Number(e.target.value))}>
                    {GAP_CHOICES.map((g) => (
                      <option key={g} value={g}>
                        {g} mm
                      </option>
                    ))}
                  </select>
                </label>
                {onePerPlate ? (
                  <PlateOrder
                    plates={rowPlates}
                    objects={objects}
                    excluded={excluded}
                    names={plateNames ?? {}}
                    gapMm={gapMm}
                    onMove={movePlate}
                  />
                ) : (
                <BeltStrip
                  order={order.filter((i) => !excluded.has(i) && byIndex.has(i))}
                  byIndex={byIndex}
                  thumbnails={thumbnails}
                  gapMm={gapMm}
                  onReorder={(visible) =>
                    onOrderChange([...visible, ...order.filter((i) => excluded.has(i) || !byIndex.has(i))])
                  }
                />
                )}
              </>
            )}
          </div>
        )}
      </div>

      <div className="object-picker-footer">
        <span className="object-picker-count">
          {selectedCount} of {objects.length} selected
        </span>
        <button type="button" className="object-picker-secondary" onClick={() => setAll(false)}>
          Select none
        </button>
        <button type="button" className="object-picker-secondary" onClick={() => setAll(true)}>
          Select all
        </button>
        <button type="button" className="object-picker-done" onClick={onClose} disabled={selectedCount === 0}>
          Done
        </button>
      </div>
    </div>
  )
}

interface BeltStripProps {
  order: number[]
  byIndex: Map<number, ObjectInfo>
  thumbnails: Record<number, string>
  gapMm: number
  onReorder: (visibleOrder: number[]) => void
}

// The kept objects as blocks along the belt, widths and gaps to scale
// (belt-travel length is each object's depth). The left-most block prints
// first. Drag a block, or focus it and use the arrow keys, to reorder.
function BeltStrip({ order, byIndex, thumbnails, gapMm, onReorder }: BeltStripProps) {
  const stripRef = useRef<HTMLDivElement>(null)
  const [dragging, setDragging] = useState<number | null>(null)
  // Everything the window-level drag handlers need, kept current without
  // re-subscribing them: pointer events can arrive faster than React
  // re-renders, so the drop position is computed from this, not the DOM.
  const latest = useRef({ order, byIndex, gapMm, onReorder })
  useEffect(() => {
    latest.current = { order, byIndex, gapMm, onReorder }
  })

  const lengths = order.map((i) => Math.max(byIndex.get(i)?.depth_mm ?? 0, 1))
  const total = lengths.reduce((a, b) => a + b, 0) + gapMm * Math.max(order.length - 1, 0)

  const move = (index: number, to: number) => {
    const cur = latest.current.order
    const from = cur.indexOf(index)
    if (from < 0 || to < 0 || to >= cur.length || to === from) return
    const next = [...cur]
    next.splice(from, 1)
    next.splice(to, 0, index)
    latest.current.order = next
    latest.current.onReorder(next)
  }

  // While a block is held, follow the pointer on the window. (Pointer
  // capture on the block does not survive React moving it in the DOM.)
  useEffect(() => {
    if (dragging === null) return
    const onMove = (e: PointerEvent) => {
      const strip = stripRef.current
      if (!strip) return
      const rect = strip.getBoundingClientRect()
      const style = getComputedStyle(strip)
      const padLeft = parseFloat(style.paddingLeft) || 0
      const inner = rect.width - padLeft - (parseFloat(style.paddingRight) || 0)
      const { order: cur, byIndex: objs, gapMm: gap } = latest.current
      const curLengths = cur.map((i) => Math.max(objs.get(i)?.depth_mm ?? 0, 1))
      const curTotal = curLengths.reduce((s, n) => s + n, 0) + gap * Math.max(cur.length - 1, 0)
      // The dragged block goes after every other block whose centre is to
      // its left, using the same to-scale layout the strip is drawn with.
      let cursor = 0
      let blocksToLeft = 0
      cur.forEach((other, pos) => {
        const centre = rect.left + padLeft + ((cursor + curLengths[pos] / 2) / curTotal) * inner
        if (other !== dragging && centre < e.clientX) blocksToLeft += 1
        cursor += curLengths[pos] + gap
      })
      move(dragging, blocksToLeft)
    }
    const stop = () => setDragging(null)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', stop)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dragging])

  return (
    <div className="belt-strip-wrap">
      <div className="belt-strip-caption">
        <span>Print order, first on the left</span>
        <span>
          belt travels → · about {Math.round(total)} mm
        </span>
      </div>
      <div className="belt-strip" ref={stripRef} style={{ columnGap: `${(gapMm / total) * 100}%` }}>
        {order.map((index, pos) => {
          const o = byIndex.get(index)
          if (!o) return null
          return (
            <div
              key={index}
              className={`belt-block${dragging === index ? ' dragging' : ''}`}
              style={{ width: `${(lengths[pos] / total) * 100}%` }}
              tabIndex={0}
              role="button"
              aria-label={`${o.name}, position ${pos + 1} of ${order.length}. Drag, or use the arrow keys, to change the print order.`}
              title={o.name}
              onPointerDown={(e) => {
                e.preventDefault()
                setDragging(index)
              }}
              onKeyDown={(e) => {
                if (e.key === 'ArrowLeft') {
                  e.preventDefault()
                  move(index, pos - 1)
                } else if (e.key === 'ArrowRight') {
                  e.preventDefault()
                  move(index, pos + 1)
                }
              }}
            >
              {thumbnails[index] ? (
                <img src={thumbnails[index]} alt="" draggable={false} />
              ) : (
                <span>{index + 1}</span>
              )}
              <span className="belt-block-order">{pos + 1}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

interface PlateOrderProps {
  plates: number[]
  objects: ObjectInfo[]
  excluded: Set<number>
  names: Record<number, string>
  gapMm: number
  onMove: (plate: number, by: -1 | 1) => void
}

// The plates in the order they come along the belt (the first prints first), each as one block that keeps
// its objects' arrangement. Move one earlier or later with its arrows.
function PlateOrder({ plates, objects, excluded, names, gapMm, onMove }: PlateOrderProps) {
  return (
    <div className="plate-order">
      <p className="auth-hint">
        Each plate goes along the belt as one block, one after the other, {gapMm} mm apart. The first one prints first.
      </p>
      <ol>
        {plates.map((plate, at) => {
          const members = objects.filter((o) => o.plate === plate && !excluded.has(o.index))
          const depth =
            Math.max(...members.map((o) => o.center_y_mm + o.depth_mm / 2)) - Math.min(...members.map((o) => o.center_y_mm - o.depth_mm / 2))
          return (
            <li key={plate}>
              <span className="plate-order-name">
                {names[plate] ?? `Plate ${plate}`}
                <small>
                  {members.length} object{members.length === 1 ? '' : 's'} · {Math.round(depth)} mm along the belt
                </small>
              </span>
              <span className="plate-order-buttons">
                <button type="button" className="preview-button" aria-label="Print earlier" disabled={at === 0} onClick={() => onMove(plate, -1)}>
                  ▲
                </button>
                <button
                  type="button"
                  className="preview-button"
                  aria-label="Print later"
                  disabled={at === plates.length - 1}
                  onClick={() => onMove(plate, 1)}
                >
                  ▼
                </button>
              </span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
