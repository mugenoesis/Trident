import { useMemo, useState } from 'react'
import type { SettingDef } from '../types'

interface AdvancedSettingsProps {
  schema: SettingDef[]
  overrides: Record<string, string>
  onChange: (overrides: Record<string, string>) => void
  excludeKeys: string[]
}

function renderInput(def: SettingDef, value: string, onChange: (v: string) => void) {
  if (def.type === 'bool') {
    return (
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="1">true</option>
        <option value="0">false</option>
      </select>
    )
  }
  if (def.enum_values?.length) {
    return (
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {def.enum_values.map((v) => (
          <option key={v} value={v}>
            {v}
          </option>
        ))}
      </select>
    )
  }
  const numeric = ['int', 'float', 'percent', 'floats', 'ints'].includes(def.type)
  return (
    <input
      type={numeric ? 'text' : 'text'}
      inputMode={numeric ? 'decimal' : undefined}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

// 787 settings is too many to render at once -- search-to-add keeps the UI
// usable while still exposing everything the CLI does (see GET
// /settings/schema, backed by --help-json).
export default function AdvancedSettings({
  schema,
  overrides,
  onChange,
  excludeKeys,
}: AdvancedSettingsProps) {
  const [query, setQuery] = useState('')

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return []
    const excluded = new Set(excludeKeys)
    return schema
      .filter(
        (s) =>
          !excluded.has(s.key) &&
          !(s.key in overrides) &&
          (s.key.toLowerCase().includes(q) || s.label?.toLowerCase().includes(q)),
      )
      .slice(0, 30)
  }, [schema, query, overrides, excludeKeys])

  const addOverride = (def: SettingDef) => {
    const initial = def.default === null || def.default === undefined ? '' : String(def.default)
    onChange({ ...overrides, [def.key]: initial })
    setQuery('')
  }

  const removeOverride = (key: string) => {
    const next = { ...overrides }
    delete next[key]
    onChange(next)
  }

  const setValue = (key: string, value: string) => onChange({ ...overrides, [key]: value })

  return (
    <details className="advanced-settings">
      <summary>Advanced settings ({schema.length} available)</summary>

      <div className="advanced-search">
        <input
          type="text"
          placeholder="Search settings by name, e.g. “skirt”, “support”, “temperature”…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {results.length > 0 && (
          <ul className="advanced-results">
            {results.map((def) => (
              <li key={def.key}>
                <button type="button" onClick={() => addOverride(def)}>
                  <strong>{def.label ?? def.key}</strong>
                  <span className="advanced-key">{def.key}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {Object.keys(overrides).length > 0 && (
        <table className="advanced-overrides">
          <tbody>
            {Object.entries(overrides).map(([key, value]) => {
              const def = schema.find((s) => s.key === key)
              return (
                <tr key={key}>
                  <td>{def?.label ?? key}</td>
                  <td>{def ? renderInput(def, value, (v) => setValue(key, v)) : value}</td>
                  <td>
                    <button type="button" onClick={() => removeOverride(key)} aria-label={`Remove ${key}`}>
                      ✕
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </details>
  )
}
