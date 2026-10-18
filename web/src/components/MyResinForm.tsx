import { useState } from 'react';

interface MyResinFormProps {
	// Whether the resin chosen is one the user made (and so can be deleted).
	chosenIsMine: boolean;
	canSave: boolean;
	onSave: (name: string) => Promise<unknown>;
	onDelete: () => Promise<unknown>;
}

// "Make my own resin based on this config…": names the values on screen and keeps them as a resin of the user's own.
export default function MyResinForm({ chosenIsMine, canSave, onSave, onDelete }: MyResinFormProps) {
	const [open, setOpen] = useState(false);
	const [name, setName] = useState('');
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const run = (action: () => Promise<unknown>, done?: () => void) => {
		setBusy(true);
		setError(null);
		action()
			.then(done)
			.catch((err: Error) => setError(err.message))
			.finally(() => setBusy(false));
	};

	const submit = (e: React.FormEvent) => {
		e.preventDefault();
		run(
			() => onSave(name.trim()),
			() => {
				setOpen(false);
				setName('');
			},
		);
	};

	return (
		<div className="my-resin">
			{open ? (
				<form className="auth-form" onSubmit={submit}>
					<label htmlFor="my-resin-name">Name of your resin</label>
					<input id="my-resin-name" value={name} onChange={(e) => setName(e.target.value)} />
					<div className="auth-form-actions">
						<button type="submit" disabled={busy || !name.trim()}>
							{busy ? 'Saving…' : 'Save resin'}
						</button>
						<button type="button" className="link-button" disabled={busy} onClick={() => setOpen(false)}>
							Cancel
						</button>
					</div>
				</form>
			) : (
				<button type="button" className="link-button" disabled={!canSave} onClick={() => setOpen(true)}>
					Make my own resin based on this config…
				</button>
			)}
			{chosenIsMine && (
				<button type="button" className="link-button danger-text" disabled={busy} onClick={() => run(onDelete)}>
					Delete my resin
				</button>
			)}
			{error && <div className="job-error">{error}</div>}
		</div>
	);
}
