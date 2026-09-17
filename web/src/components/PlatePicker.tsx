import type { PlateInfo } from '../types'

interface PlatePickerProps {
  plates: PlateInfo[]
  plateIndex: number | null
  onChange: (index: number) => void
}

// Shown only when an uploaded .3mf's parsed plate list has more than one
// entry (App.tsx) -- slicing a specific plate requires picking one first
// rather than slicing every plate in the file.
export default function PlatePicker({ plates, plateIndex, onChange }: PlatePickerProps) {
  return (
    <div className="field-group plate-picker">
      <span>This file has multiple plates -- pick one to slice</span>
      <div className="plate-picker-options">
        {plates.map((plate) => (
          <label key={plate.index} className="plate-picker-option">
            <input
              type="radio"
              name="plate-picker"
              checked={plateIndex === plate.index}
              onChange={() => onChange(plate.index)}
            />
            {plate.name ?? `Plate ${plate.index}`}
            {plate.object_count != null
              ? ` (${plate.object_count} object${plate.object_count === 1 ? '' : 's'})`
              : ''}
          </label>
        ))}
      </div>
    </div>
  )
}
