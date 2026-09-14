import type { SettingDef } from '../types'

export interface QuickSettingsValues {
  layer_height: string
  sparse_infill_density: string
  wall_loops: string
  sparse_infill_pattern: string
}

interface QuickSettingsProps {
  schema: SettingDef[]
  values: QuickSettingsValues
  onChange: (values: QuickSettingsValues) => void
}

const KEYS: (keyof QuickSettingsValues)[] = [
  'layer_height',
  'sparse_infill_density',
  'wall_loops',
  'sparse_infill_pattern',
]

function findDef(schema: SettingDef[], key: string): SettingDef | undefined {
  return schema.find((s) => s.key === key)
}

// The four settings people adjust for almost every print, kept always
// visible per the design brief -- everything else lives in AdvancedSettings.
export default function QuickSettings({ schema, values, onChange }: QuickSettingsProps) {
  const set = (key: keyof QuickSettingsValues, value: string) =>
    onChange({ ...values, [key]: value })

  const patternDef = findDef(schema, 'sparse_infill_pattern')

  return (
    <div className="field-group">
      <label>
        Layer height (mm)
        <input
          type="number"
          step="0.02"
          min="0.04"
          max="0.6"
          value={values.layer_height}
          onChange={(e) => set('layer_height', e.target.value)}
        />
      </label>

      <label>
        Infill density: {values.sparse_infill_density}%
        <input
          type="range"
          min="0"
          max="100"
          step="5"
          value={values.sparse_infill_density}
          onChange={(e) => set('sparse_infill_density', e.target.value)}
        />
      </label>

      <label>
        Wall loops
        <input
          type="number"
          step="1"
          min="1"
          max="10"
          value={values.wall_loops}
          onChange={(e) => set('wall_loops', e.target.value)}
        />
      </label>

      <label>
        Infill pattern
        <select
          value={values.sparse_infill_pattern}
          onChange={(e) => set('sparse_infill_pattern', e.target.value)}
        >
          {(patternDef?.enum_values ?? [values.sparse_infill_pattern]).map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}

export function defaultQuickSettings(schema: SettingDef[]): QuickSettingsValues {
  const def = (key: string, fallback: string) => {
    const value = findDef(schema, key)?.default
    return value === null || value === undefined ? fallback : String(value).replace('%', '')
  }
  return {
    layer_height: def('layer_height', '0.2'),
    sparse_infill_density: def('sparse_infill_density', '15'),
    wall_loops: def('wall_loops', '2'),
    sparse_infill_pattern: def('sparse_infill_pattern', 'grid'),
  }
}

export { KEYS as QUICK_SETTING_KEYS }
