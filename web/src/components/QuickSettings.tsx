import type { SettingDef } from '../types'

export interface QuickSettingsValues {
  layer_height: string
  sparse_infill_density: string
  wall_loops: string
  sparse_infill_pattern: string
  curr_bed_type: string
  enable_support: string
  support_type: string
  // Bound to the schema/override key "support_on_build_plate_only" -- kept
  // as its own field name since "support_buildplate_only" is a
  // same-named-looking but unrelated SLA-only option that no-ops for FDM
  // (see App.tsx's slice-request override for the full story).
  support_buildplate_only: string
  // The wipe/prime tower -- purges leftover filament on the nozzle after a
  // color change so it doesn't show up in the next layer. App.tsx defaults
  // this on whenever the selected printer has more than one filament slot
  // configured (a color change becomes possible), but it's a plain toggle
  // here same as any other -- the user can always turn it back off.
  enable_prime_tower: string
  // Seam position and brim type start empty ("Profile default") and are
  // only sent as overrides once the user picks something -- unlike the
  // fields above, a schema default here would silently replace whatever the
  // selected process profile (e.g. a belt printer's own brim choice) sets.
  seam_position: string
  brim_type: string
}

interface QuickSettingsProps {
  schema: SettingDef[]
  values: QuickSettingsValues
  onChange: (values: QuickSettingsValues) => void
  // Belt printers lay their brim onto the tilted belt, which only has the
  // modes in BELT_BRIM_TYPES: Auto, Mouse ears and Painted all come out as a
  // plain outer brim there, so they are not offered. Leading edge only is the
  // reverse: a belt-only mode (elsewhere it degrades to an outer brim).
  isBelt?: boolean
}

const KEYS: (keyof QuickSettingsValues)[] = [
  'layer_height',
  'sparse_infill_density',
  'wall_loops',
  'sparse_infill_pattern',
  'curr_bed_type',
  'enable_support',
  'support_type',
  'support_buildplate_only',
  'enable_prime_tower',
  'seam_position',
  'brim_type',
]

// The engine's raw enum values read poorly in a dropdown ("aligned_back").
const SEAM_LABELS: Record<string, string> = {
  nearest: 'Nearest',
  aligned: 'Aligned',
  aligned_back: 'Aligned (back)',
  back: 'Rear',
  random: 'Random',
}
const BRIM_LABELS: Record<string, string> = {
  auto_brim: 'Auto',
  brim_ears: 'Mouse ears',
  painted: 'Painted',
  outer_only: 'Outer only',
  inner_only: 'Inner only',
  outer_and_inner: 'Outer and inner',
  no_brim: 'None',
  leading_edge_only: 'Leading edge only',
}

export const BELT_BRIM_TYPES = ['outer_only', 'inner_only', 'outer_and_inner', 'leading_edge_only', 'no_brim']

function findDef(schema: SettingDef[], key: string): SettingDef | undefined {
  return schema.find((s) => s.key === key)
}

// The four settings people adjust for almost every print, kept always
// visible per the design brief -- everything else lives in AdvancedSettings.
export default function QuickSettings({ schema, values, onChange, isBelt }: QuickSettingsProps) {
  const set = (key: keyof QuickSettingsValues, value: string) =>
    onChange({ ...values, [key]: value })

  const patternDef = findDef(schema, 'sparse_infill_pattern')
  const bedTypeDef = findDef(schema, 'curr_bed_type')
  const supportTypeDef = findDef(schema, 'support_type')
  const seamDef = findDef(schema, 'seam_position')
  const brimDef = findDef(schema, 'brim_type')
  const supportEnabled = values.enable_support === '1'

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

      <label>
        Seam position
        <select value={values.seam_position} onChange={(e) => set('seam_position', e.target.value)}>
          <option value="">Profile default</option>
          {(seamDef?.enum_values ?? []).map((v) => (
            <option key={v} value={v}>
              {SEAM_LABELS[v] ?? v}
            </option>
          ))}
        </select>
      </label>

      <label>
        Brim type
        <select value={values.brim_type} onChange={(e) => set('brim_type', e.target.value)}>
          <option value="">Profile default</option>
          {(brimDef?.enum_values ?? [])
            .filter((v) => (isBelt ? BELT_BRIM_TYPES.includes(v) : v !== 'leading_edge_only'))
            .map((v) => (
            <option key={v} value={v}>
              {BRIM_LABELS[v] ?? v}
            </option>
          ))}
        </select>
      </label>

      <label>
        Build plate
        <select
          value={values.curr_bed_type}
          onChange={(e) => set('curr_bed_type', e.target.value)}
        >
          {(bedTypeDef?.enum_values ?? [values.curr_bed_type]).map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </label>

      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={supportEnabled}
          onChange={(e) => set('enable_support', e.target.checked ? '1' : '0')}
        />
        Enable support
      </label>

      <label>
        Support type
        <select
          value={values.support_type}
          disabled={!supportEnabled}
          onChange={(e) => set('support_type', e.target.value)}
        >
          {(supportTypeDef?.enum_values ?? [values.support_type]).map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </label>

      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={values.support_buildplate_only === '1'}
          disabled={!supportEnabled}
          onChange={(e) => set('support_buildplate_only', e.target.checked ? '1' : '0')}
        />
        Support on build plate only
      </label>

      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={values.enable_prime_tower === '1'}
          onChange={(e) => set('enable_prime_tower', e.target.checked ? '1' : '0')}
        />
        Enable prime/wipe tower
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
    curr_bed_type: def('curr_bed_type', 'Cool Plate'),
    enable_support: def('enable_support', '0'),
    support_type: def('support_type', 'normal(auto)'),
    support_buildplate_only: def('support_on_build_plate_only', '0'),
    // Matches OrcaSlicer's own baseline default (false) -- App.tsx turns
    // this on automatically once a multi-slot printer is selected.
    enable_prime_tower: def('enable_prime_tower', '0'),
    seam_position: '',
    brim_type: '',
  }
}

export { KEYS as QUICK_SETTING_KEYS }
