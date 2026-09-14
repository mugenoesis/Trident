import { useEffect, useState } from 'react'
import type { Dimensions } from '../dimensions'

interface ScaleControlsProps {
  dimensions: Dimensions
  onApply: (factors: Dimensions) => void
  applying: boolean
}

type DraftDimensions = Record<keyof Dimensions, string>

const AXES: (keyof Dimensions)[] = ['x', 'y', 'z']

const toDraft = (dims: Dimensions): DraftDimensions => ({
  x: dims.x.toFixed(1),
  y: dims.y.toFixed(1),
  z: dims.z.toFixed(1),
})

// Manual scale entry: three editable dimension boxes plus a uniform-scaling
// toggle, shown once a model is loaded. Separate from the auto-fit toast
// (App.tsx) -- that one reacts to a printer's bed size, this is a plain
// "type the size you want" control. Both end up calling the same
// scaleStlFile() + re-upload path.
export default function ScaleControls({ dimensions, onApply, applying }: ScaleControlsProps) {
  // Kept as strings, not numbers: a controlled numeric input showing a
  // derived number snaps back on every keystroke otherwise (can't clear the
  // box to type a new value) -- same reason QuickSettings' values are
  // strings.
  const [draft, setDraft] = useState<DraftDimensions>(() => toDraft(dimensions))
  const [uniform, setUniform] = useState(true)

  // Reflect the model's actual current size whenever it changes (a fresh
  // upload, or after a scale -- ours or the auto-fit toast's -- was applied)
  // rather than leaving stale numbers in the boxes.
  useEffect(() => setDraft(toDraft(dimensions)), [dimensions])

  const handleChange = (axis: keyof Dimensions, value: string) => {
    if (!uniform) {
      setDraft((prev) => ({ ...prev, [axis]: value }))
      return
    }
    const n = Number(value)
    if (value === '' || !Number.isFinite(n) || n <= 0) {
      setDraft((prev) => ({ ...prev, [axis]: value }))
      return
    }
    const ratio = n / dimensions[axis]
    setDraft({
      x: axis === 'x' ? value : (dimensions.x * ratio).toFixed(1),
      y: axis === 'y' ? value : (dimensions.y * ratio).toFixed(1),
      z: axis === 'z' ? value : (dimensions.z * ratio).toFixed(1),
    })
  }

  const draftNums = ((): Dimensions | null => {
    const x = Number(draft.x)
    const y = Number(draft.y)
    const z = Number(draft.z)
    return [x, y, z].every((n) => Number.isFinite(n) && n > 0) ? { x, y, z } : null
  })()

  const hasChanges =
    draftNums !== null && AXES.some((axis) => Math.abs(draftNums[axis] - dimensions[axis]) > 0.05)

  const handleApply = () => {
    if (!draftNums) return
    onApply({
      x: draftNums.x / dimensions.x,
      y: draftNums.y / dimensions.y,
      z: draftNums.z / dimensions.z,
    })
  }

  return (
    <div className="scale-controls">
      <label className="checkbox-label">
        <input type="checkbox" checked={uniform} onChange={(e) => setUniform(e.target.checked)} />
        Uniform scaling
      </label>

      <div className="scale-axes">
        {AXES.map((axis) => (
          <label key={axis}>
            {axis.toUpperCase()} (mm)
            <input
              type="number"
              min="0.1"
              step="0.1"
              value={draft[axis]}
              onChange={(e) => handleChange(axis, e.target.value)}
            />
          </label>
        ))}
      </div>

      <button type="button" onClick={handleApply} disabled={!hasChanges || applying}>
        {applying ? 'Scaling…' : 'Apply scale'}
      </button>
    </div>
  )
}
