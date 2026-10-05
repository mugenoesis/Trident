import { useRef } from 'react'
import type { KeyboardEvent, PointerEvent } from 'react'

interface AxisSliderProps {
  value: number
  min: number
  max: number
  step?: number
  // Vertical sliders have their maximum at the top.
  orientation?: 'horizontal' | 'vertical'
  disabled?: boolean
  ariaLabel: string
  // Shown to assistive tech instead of the bare number ("12 degrees").
  valueText?: string
  // A small tick at this value (the zero of a rotation).
  tick?: number
  onChange: (value: number) => void
}

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)

/**
 * A slider drawn by hand so the same control can run along the left edge of the
 * preview (vertical) and under it (horizontal), which a native range input
 * cannot do consistently across browsers. Drag, arrow keys (Shift = ten steps),
 * Home and End all work.
 */
export default function AxisSlider({
  value,
  min,
  max,
  step = 1,
  orientation = 'horizontal',
  disabled = false,
  ariaLabel,
  valueText,
  tick,
  onChange,
}: AxisSliderProps) {
  const trackRef = useRef<HTMLDivElement>(null)
  const vertical = orientation === 'vertical'
  const span = max - min
  const locked = disabled || !(span > 0)
  const fraction = span > 0 ? clamp((value - min) / span, 0, 1) : 0.5
  const position = `${(vertical ? 1 - fraction : fraction) * 100}%`

  const valueAt = (event: PointerEvent) => {
    const rect = trackRef.current?.getBoundingClientRect()
    if (!rect) return value
    const raw = vertical ? 1 - (event.clientY - rect.top) / rect.height : (event.clientX - rect.left) / rect.width
    const stepped = Math.round((min + clamp(raw, 0, 1) * span) / step) * step
    return clamp(stepped, min, max)
  }

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (locked) return
    event.currentTarget.setPointerCapture(event.pointerId)
    onChange(valueAt(event))
  }
  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (locked || !event.currentTarget.hasPointerCapture(event.pointerId)) return
    onChange(valueAt(event))
  }
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (locked) return
    const big = event.shiftKey ? 10 : 1
    const up = vertical ? ['ArrowUp', 'ArrowRight'] : ['ArrowRight', 'ArrowUp']
    const down = vertical ? ['ArrowDown', 'ArrowLeft'] : ['ArrowLeft', 'ArrowDown']
    let next: number | null = null
    if (up.includes(event.key)) next = value + step * big
    else if (down.includes(event.key)) next = value - step * big
    else if (event.key === 'Home') next = min
    else if (event.key === 'End') next = max
    if (next === null) return
    event.preventDefault()
    onChange(clamp(next, min, max))
  }

  const tickFraction = tick !== undefined && span > 0 ? clamp((tick - min) / span, 0, 1) : null

  return (
    <div
      className={`axis-slider axis-slider-${orientation}${locked ? ' axis-slider-locked' : ''}`}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
    >
      <div className="axis-slider-track" ref={trackRef}>
        {tickFraction !== null && (
          <span
            className="axis-slider-tick"
            style={vertical ? { top: `${(1 - tickFraction) * 100}%` } : { left: `${tickFraction * 100}%` }}
          />
        )}
        <div
          className="axis-slider-handle"
          role="slider"
          tabIndex={locked ? -1 : 0}
          aria-label={ariaLabel}
          aria-orientation={orientation}
          aria-valuemin={min}
          aria-valuemax={max}
          aria-valuenow={Number.isFinite(value) ? value : undefined}
          aria-valuetext={valueText}
          aria-disabled={locked || undefined}
          style={vertical ? { top: position } : { left: position }}
          onKeyDown={handleKeyDown}
        />
      </div>
    </div>
  )
}
