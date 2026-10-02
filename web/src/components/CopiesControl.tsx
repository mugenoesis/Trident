const GAP_CHOICES = [5, 10, 20, 50]
const MAX_COPIES = 50

interface CopiesControlProps {
  copies: number
  onCopiesChange: (copies: number) => void
  // Belt printers line the copies up along the belt; anything else lets the
  // slicer arrange them.
  isBelt: boolean
  gapMm: number
  onGapChange: (gapMm: number) => void
  // Belt-travel length of one copy (the selection laid out end to end), mm.
  copyLengthMm: number
}

// "Copies" stepper above the Slice button. On a belt printer a to-scale strip
// shows the copies end to end (first printed on the left).
export default function CopiesControl({ copies, onCopiesChange, isBelt, gapMm, onGapChange, copyLengthMm }: CopiesControlProps) {
  const clamp = (n: number) => Math.min(MAX_COPIES, Math.max(1, Math.round(n) || 1))
  const total = copyLengthMm * copies + gapMm * (copies - 1)
  return (
    <div className="field-group copies-control">
      <div className="copies-row">
        <span>Copies</span>
        <span className="copies-stepper">
          <button type="button" aria-label="Fewer copies" disabled={copies <= 1} onClick={() => onCopiesChange(clamp(copies - 1))}>
            −
          </button>
          <input
            type="number"
            min={1}
            max={MAX_COPIES}
            inputMode="numeric"
            aria-label="Number of copies"
            value={copies}
            onChange={(e) => onCopiesChange(clamp(Number(e.target.value)))}
          />
          <button type="button" aria-label="More copies" disabled={copies >= MAX_COPIES} onClick={() => onCopiesChange(clamp(copies + 1))}>
            +
          </button>
        </span>
      </div>
      {copies > 1 && !isBelt && <span className="copies-note">The slicer arranges the copies on the plate.</span>}
      {copies > 1 && isBelt && (
        <>
          <label className="copies-row">
            <span>Gap between copies</span>
            <select value={gapMm} onChange={(e) => onGapChange(Number(e.target.value))}>
              {GAP_CHOICES.map((g) => (
                <option key={g} value={g}>
                  {g} mm
                </option>
              ))}
            </select>
          </label>
          {copyLengthMm > 0 && (
            <div className="copies-strip" style={{ columnGap: `${(gapMm / total) * 100}%` }} aria-hidden="true">
              {Array.from({ length: copies }, (_, i) => (
                <span key={i} className="copies-block" style={{ width: `${(copyLengthMm / total) * 100}%` }}>
                  {i + 1}
                </span>
              ))}
            </div>
          )}
          <span className="copies-note">Lined up along the belt, first printed on the left · about {Math.round(total)} mm</span>
        </>
      )}
    </div>
  )
}
