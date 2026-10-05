import type { BedSize } from '../dimensions'
import { defaultPlacement } from '../dimensions'
import type { Placement } from '../types'

interface PositionPanelProps {
  bedSize: BedSize
  supportEnabled: boolean
  // null = the slicer's own default spot.
  placement: Placement | null
  onPlacementChange: (placement: Placement | null) => void
  onOpen: () => void
  // A file with several plates: what is being worked on, shown instead of a position.
  plateSummary?: string
}

// Where the model sits on the plate, with the button that opens the "Rotate and move"
// window (RotateMoveDialog) where it is turned and placed.
export default function PositionPanel({ bedSize, supportEnabled, placement, onPlacementChange, onOpen, plateSummary }: PositionPanelProps) {
  const current = placement ?? defaultPlacement(bedSize, supportEnabled)
  return (
    <div className="field-group position-panel">
      <div className="position-panel-head">
        <strong>Position</strong>
        {!plateSummary && (
          <button type="button" className="link-button" disabled={placement === null} onClick={() => onPlacementChange(null)}>
            Reset
          </button>
        )}
      </div>
      <div className="position-summary">
        <span className="auth-hint">
          {plateSummary ?? `Centre at ${(current.x - bedSize.minX).toFixed(1)}, ${(current.y - bedSize.minY).toFixed(1)} mm`}
        </span>
        <button type="button" className="preview-button" onClick={onOpen}>
          Rotate and move…
        </button>
      </div>
    </div>
  )
}
