import type { BedSize, Dimensions } from '../dimensions'
import { defaultPlacement } from '../dimensions'
import type { Placement } from '../types'

interface PositionPanelProps {
  bedSize: BedSize
  // Footprint of the model as loaded in the viewer.
  dimensions: Dimensions
  supportEnabled: boolean
  // null = the slicer's own default spot.
  placement: Placement | null
  onPlacementChange: (placement: Placement | null) => void
  onAutoOrient: () => void
  onAutoArrange: () => void
  busy: 'orient' | 'arrange' | null
}

// A belt bed is effectively endless; this is how far along it the slider goes.
const BELT_TRAVEL_MM = 400

function range(lo: number, hi: number, half: number): [number, number] {
  const min = lo + half
  const max = hi - half
  // A model larger than the bed has no valid range; pin it to the middle.
  return min <= max ? [min, max] : [(lo + hi) / 2, (lo + hi) / 2]
}

// Sliders for where the model sits on the plate, with the slicer's own
// auto-orient and arrange one tap away. The numbers beside the sliders are
// the footprint centre in mm from the bed's front-left corner.
export default function PositionPanel({
  bedSize,
  dimensions,
  supportEnabled,
  placement,
  onPlacementChange,
  onAutoOrient,
  onAutoArrange,
  busy,
}: PositionPanelProps) {
  const current = placement ?? defaultPlacement(bedSize, supportEnabled)
  const [xMin, xMax] = range(bedSize.minX, bedSize.minX + bedSize.width, dimensions.x / 2)
  const yTop = bedSize.beltPrinterInfiniteY ? bedSize.minY + BELT_TRAVEL_MM + dimensions.y : bedSize.minY + bedSize.depth
  const [yMin, yMax] = range(bedSize.minY, yTop, dimensions.y / 2)
  const set = (patch: Partial<Placement>) => onPlacementChange({ ...current, ...patch })
  const working = busy !== null

  return (
    <div className="field-group position-panel">
      <div className="position-panel-head">
        <strong>Position</strong>
        <button type="button" className="link-button" disabled={placement === null || working} onClick={() => onPlacementChange(null)}>
          Reset
        </button>
      </div>

      <label className="position-slider">
        <span className="position-slider-label">
          <span>Across the plate (X)</span>
          <strong>{(current.x - bedSize.minX).toFixed(1)} mm</strong>
        </span>
        <input
          type="range"
          min={xMin}
          max={xMax}
          step={0.5}
          value={Math.min(Math.max(current.x, xMin), xMax)}
          disabled={working || xMin === xMax}
          onChange={(e) => set({ x: Number(e.target.value) })}
        />
      </label>

      <label className="position-slider">
        <span className="position-slider-label">
          <span>{bedSize.beltPrinterInfiniteY ? 'Along the belt (Y)' : 'Front to back (Y)'}</span>
          <strong>{(current.y - bedSize.minY).toFixed(1)} mm</strong>
        </span>
        <input
          type="range"
          min={yMin}
          max={yMax}
          step={0.5}
          value={Math.min(Math.max(current.y, yMin), yMax)}
          disabled={working || yMin === yMax}
          onChange={(e) => set({ y: Number(e.target.value) })}
        />
      </label>

      <div className="position-actions">
        <button type="button" className="preview-button" disabled={working} onClick={onAutoOrient}>
          {busy === 'orient' ? 'Orienting…' : 'Auto-orient'}
        </button>
        <button type="button" className="preview-button" disabled={working} onClick={onAutoArrange}>
          {busy === 'arrange' ? 'Arranging…' : 'Auto-arrange'}
        </button>
      </div>
    </div>
  )
}
