// A preset value as one text: a list comma separated, anything else as it is.
export function settingText(v: unknown): string {
  if (Array.isArray(v)) return v.map(String).join(', ')
  return v === null || v === undefined ? '' : String(v)
}
