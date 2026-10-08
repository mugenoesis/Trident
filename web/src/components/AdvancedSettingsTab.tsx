import { useMemo, useState } from 'react'
import { settingText } from '../settingText'
import type { SettingDef } from '../types'

interface AdvancedSettingsTabProps {
  // The setting keys that can be added (the preset kind's own settings that the Basics tab does not cover).
  keys: string[]
  defs: Map<string, SettingDef>
  // key -> text, the settings changed for this preset.
  advanced: Record<string, string>
  onChange: (next: Record<string, string>) => void
  // The resolved values the preset inherits, to show what a change replaces.
  inherited: Record<string, unknown>
  // "printer" or "material", for the wording.
  noun: string
  placeholder: string
}

/**
 * Search a preset kind's settings, add the ones to change, and keep them in a list with their inherited value,
 * an editor and Remove. Shared by the New printer and New material forms.
 */
export default function AdvancedSettingsTab({ keys, defs, advanced, onChange, inherited, noun, placeholder }: AdvancedSettingsTabProps) {
  const [query, setQuery] = useState('')
  const labelFor = (def: SettingDef | undefined, value: string) => {
    const at = def?.enum_values?.indexOf(value) ?? -1
    return at >= 0 && def?.enum_labels?.[at] ? def.enum_labels[at] : value
  }

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return []
    return keys
      .filter((key) => !(key in advanced))
      .map((key) => defs.get(key))
      .filter((d): d is SettingDef => Boolean(d))
      .filter((d) => d.key.includes(q) || (d.label ?? '').toLowerCase().includes(q) || (d.description ?? '').toLowerCase().includes(q))
      .slice(0, 30)
  }, [query, keys, defs, advanced])

  const add = (def: SettingDef) => {
    const inheritedText = settingText(inherited[def.key])
    onChange({ ...advanced, [def.key]: inheritedText !== '' ? inheritedText : String(def.default ?? '') })
    setQuery('')
  }
  const setValue = (key: string, value: string) => onChange({ ...advanced, [key]: value })
  const remove = (key: string) => {
    const next = { ...advanced }
    delete next[key]
    onChange(next)
  }

  return (
    <>
      <label>
        Search {noun} settings
        <input type="text" placeholder={placeholder} value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      {query.trim() !== '' && (
        <ul className="advanced-results">
          {results.length === 0 && <li className="auth-hint">Nothing matches. The Basics tab already covers the common settings.</li>}
          {results.map((d) => (
            <li key={d.key}>
              <span>
                {d.label || d.key}
                <small>
                  {(d.description ?? '').slice(0, 110)} · {d.key}
                </small>
              </span>
              <button type="button" className="preview-button" onClick={() => add(d)}>
                Add
              </button>
            </li>
          ))}
        </ul>
      )}
      <h3 className="material-section">Changed for this {noun} ({Object.keys(advanced).length})</h3>
      {Object.keys(advanced).length === 0 && <p className="auth-hint">Nothing yet. Search above to add a setting.</p>}
      <ul className="advanced-results advanced-added">
        {Object.entries(advanced).map(([key, value]) => {
          const def = defs.get(key)
          const was = settingText(inherited[key])
          const multiline = key.endsWith('_gcode') || value.includes('\n')
          return (
            <li key={key}>
              <span>
                {def?.label || key}
                <small>
                  {was !== '' && was !== value ? `inherited: ${was.slice(0, 60)} · ` : ''}
                  {key}
                </small>
              </span>
              <span className="advanced-edit">
                {def?.type === 'bool' ? (
                  <select value={value} onChange={(e) => setValue(key, e.target.value)}>
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                ) : def?.enum_values?.length ? (
                  <select value={value} onChange={(e) => setValue(key, e.target.value)}>
                    {!def.enum_values.includes(value) && <option value={value}>{value}</option>}
                    {def.enum_values.map((v) => (
                      <option key={v} value={v}>
                        {labelFor(def, v)}
                      </option>
                    ))}
                  </select>
                ) : multiline ? (
                  <textarea className="gcode-box" rows={4} value={value} spellCheck={false} onChange={(e) => setValue(key, e.target.value)} />
                ) : (
                  <input type="text" value={value} onChange={(e) => setValue(key, e.target.value)} />
                )}
                <button type="button" className="link-button" onClick={() => remove(key)}>
                  Remove
                </button>
              </span>
            </li>
          )
        })}
      </ul>
      <p className="auth-hint">Removing a setting puts back the value the {noun} inherits.</p>
    </>
  )
}
