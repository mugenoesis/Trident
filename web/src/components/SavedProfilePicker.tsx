import { useState } from 'react'

interface ProfileLike {
  id: string
  name: string
}

// One row in "Manage <label>s": name (or an inline rename input),
// Rename/Duplicate/Delete. Generic over material profiles and settings
// profiles alike -- both are just a named, saved snapshot of some of the
// current App state, rename/duplicate/delete work identically either way.
function ProfileManageRow<T extends ProfileLike>({
  profile,
  onRename,
  onDuplicate,
  onDelete,
}: {
  profile: T
  onRename: (id: string, name: string) => Promise<unknown>
  onDuplicate: (id: string) => void
  onDelete: (id: string) => void
}) {
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState(profile.name)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submitRename = (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    onRename(profile.id, name)
      .then(() => setRenaming(false))
      .catch((err: Error) => setError(err.message))
      .finally(() => setBusy(false))
  }

  if (renaming) {
    return (
      <li>
        <form className="rename-form" onSubmit={submitRename}>
          <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          <button type="submit" disabled={busy || !name}>
            {busy ? 'Saving…' : 'Save'}
          </button>
          <button
            type="button"
            className="link-button"
            disabled={busy}
            onClick={() => {
              setRenaming(false)
              setName(profile.name)
              setError(null)
            }}
          >
            Cancel
          </button>
          {error && <span className="job-error">{error}</span>}
        </form>
      </li>
    )
  }

  return (
    <li>
      <span>{profile.name}</span>
      <button type="button" className="link-button" onClick={() => setRenaming(true)}>
        Rename
      </button>
      <button type="button" className="link-button" onClick={() => onDuplicate(profile.id)}>
        Duplicate
      </button>
      <button type="button" className="link-button job-delete" onClick={() => onDelete(profile.id)}>
        Delete
      </button>
    </li>
  )
}

interface SavedProfilePickerProps<T extends ProfileLike> {
  // Plain lowercase noun used in labels/placeholders, e.g. "material
  // profile" or "settings profile".
  label: string
  profiles: T[]
  selectedId: string | null
  onSelect: (profile: T) => void
  onDeselect: () => void
  onSave: (name: string) => Promise<unknown>
  onUpdate: () => Promise<unknown>
  onRename: (id: string, name: string) => Promise<unknown>
  onDuplicate: (id: string) => void
  onDelete: (id: string) => void
}

// A picker for one of the two independently-saveable snapshots of the
// current settings panel (material choice, or print-quality settings) --
// pick one to restore it, or save whatever's currently dialed in as a new
// one. Used twice (once per kind) inside App.tsx's "Material" and
// "Settings" sections; extracted out of SavedPrinters.tsx, which used to
// render this same shape just for materials.
export default function SavedProfilePicker<T extends ProfileLike>({
  label,
  profiles,
  selectedId,
  onSelect,
  onDeselect,
  onSave,
  onUpdate,
  onRename,
  onDuplicate,
  onDelete,
}: SavedProfilePickerProps<T>) {
  const [saving, setSaving] = useState(false)
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [updateBusy, setUpdateBusy] = useState(false)
  const [updateDone, setUpdateDone] = useState(false)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    onSave(name)
      .then(() => {
        setSaving(false)
        setName('')
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setBusy(false))
  }

  const runUpdate = () => {
    setUpdateBusy(true)
    setUpdateDone(false)
    onUpdate()
      .then(() => setUpdateDone(true))
      .catch((err: Error) => alert(`Failed to update ${label}: ${err.message}`))
      .finally(() => setUpdateBusy(false))
  }

  const selected = profiles.find((p) => p.id === selectedId) ?? null

  return (
    <div className="saved-profile-picker">
      <div className="field-group">
        <label>
          {label.charAt(0).toUpperCase() + label.slice(1)}
          <select
            value={selectedId ?? ''}
            onChange={(e) => {
              const profile = profiles.find((p) => p.id === e.target.value)
              if (profile) onSelect(profile)
              else onDeselect()
            }}
          >
            <option value="">{`— choose a ${label} —`}</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {selected && (
        <div className="material-update-actions">
          <button type="button" className="preview-button" disabled={updateBusy} onClick={runUpdate}>
            {updateBusy ? 'Updating…' : `Update "${selected.name}"`}
          </button>
          {updateDone && <span className="job-hint">Updated.</span>}
        </div>
      )}

      {!saving ? (
        <button type="button" className="link-button" onClick={() => setSaving(true)}>
          {selected ? 'Save as new profile…' : `Save current settings as a ${label}…`}
        </button>
      ) : (
        <form className="auth-form" onSubmit={submit}>
          <label>
            Name (e.g. "PLA", "0.2mm Standard")
            <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </label>
          <div className="auth-form-actions">
            <button type="submit" disabled={busy || !name}>
              {busy ? 'Saving…' : `Save ${label}`}
            </button>
            <button
              type="button"
              className="link-button"
              disabled={busy}
              onClick={() => {
                setSaving(false)
                setName('')
                setError(null)
              }}
            >
              Cancel
            </button>
          </div>
          {error && <div className="job-error">{error}</div>}
        </form>
      )}

      {profiles.length > 0 && (
        <details className="job-history">
          <summary>{`Manage ${label}s (${profiles.length})`}</summary>
          <ul>
            {profiles.map((p) => (
              <ProfileManageRow
                key={p.id}
                profile={p}
                onRename={onRename}
                onDuplicate={onDuplicate}
                onDelete={onDelete}
              />
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
