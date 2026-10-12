import { useState } from 'react';
import type { AuthStatus, SampleModelSummary } from '../types';

interface SettingsMenuProps {
	status: AuthStatus;
	onSwitchToMulti: (username: string, password: string) => Promise<unknown>;
	onSwitchToSingle: () => Promise<unknown>;
	onCreateUser: (username: string, password: string) => Promise<unknown>;
	onLogout: () => Promise<unknown>;
	sampleModels: SampleModelSummary[];
	onLoadSample: (sampleId: string) => Promise<unknown>;
}

// Small header gear -> dropdown panel. The only place mode/account
// management lives outside the first-run gate: switching single -> multi
// (or back), adding a household account, and logging out.
export default function SettingsMenu({
	status,
	onSwitchToMulti,
	onSwitchToSingle,
	onCreateUser,
	onLogout,
	sampleModels,
	onLoadSample,
}: SettingsMenuProps) {
	const [open, setOpen] = useState(false);
	const [form, setForm] = useState<MenuForm>('none');
	const [username, setUsername] = useState('');
	const [password, setPassword] = useState('');
	const [error, setError] = useState<string | null>(null);
	const [busy, setBusy] = useState(false);
	const [loadingSampleId, setLoadingSampleId] = useState<string | null>(null);

	const loadSample = (sampleId: string) => {
		setLoadingSampleId(sampleId);
		setError(null);
		onLoadSample(sampleId)
			.then(() => {
				setOpen(false);
				resetForm();
			})
			.catch((err: Error) => setError(err.message))
			.finally(() => setLoadingSampleId(null));
	};

	const resetForm = () => {
		setForm('none');
		setUsername('');
		setPassword('');
		setError(null);
	};

	const submit = (action: (u: string, p: string) => Promise<unknown>) => (e: React.FormEvent) => {
		e.preventDefault();
		setBusy(true);
		setError(null);
		action(username, password)
			.then(() => resetForm())
			.catch((err: Error) => setError(err.message))
			.finally(() => setBusy(false));
	};

	const confirmDowngrade = () => {
		setBusy(true);
		setError(null);
		onSwitchToSingle()
			.then(() => resetForm())
			.catch((err: Error) => setError(err.message))
			.finally(() => setBusy(false));
	};

	return (
		<div className="settings-menu">
			<button
				type="button"
				className="settings-gear"
				aria-label="Settings"
				onClick={() => {
					setOpen((o) => !o);
					resetForm();
				}}
			>
				⚙
			</button>
			{open && (
				<div className="settings-panel">
					{form === 'none' && <AccountLinks status={status} onChoose={setForm} onLogout={onLogout} />}
					{form === 'samples' && (
						<SamplesList samples={sampleModels} loadingId={loadingSampleId} error={error} onLoad={loadSample} onCancel={resetForm} />
					)}
					{form === 'downgrade' && <DowngradePanel busy={busy} error={error} onConfirm={confirmDowngrade} onCancel={resetForm} />}
					{(form === 'switch' || form === 'add') && (
						<CredentialsForm
							mode={form}
							username={username}
							password={password}
							busy={busy}
							error={error}
							onUsername={setUsername}
							onPassword={setPassword}
							onSubmit={submit(form === 'switch' ? onSwitchToMulti : onCreateUser)}
							onCancel={resetForm}
						/>
					)}
				</div>
			)}
		</div>
	);
}

type MenuForm = 'none' | 'switch' | 'add' | 'downgrade' | 'samples';

function AccountLinks({
	status,
	onChoose,
	onLogout,
}: {
	status: AuthStatus;
	onChoose: (form: MenuForm) => void;
	onLogout: () => Promise<unknown>;
}) {
	return (
		<>
			{status.mode === 'single' && (
				<>
					<div className="settings-status">Single-user mode</div>
					<button type="button" className="link-button" onClick={() => onChoose('switch')}>
						Switch to multi-user…
					</button>
				</>
			)}
			{status.mode === 'multi' && (
				<>
					<div className="settings-status">Signed in as {status.username}</div>
					<button type="button" className="link-button" onClick={() => onChoose('add')}>
						Add another user…
					</button>
					<button type="button" className="link-button" onClick={() => onLogout()}>
						Log out
					</button>
					<button type="button" className="link-button danger-text" onClick={() => onChoose('downgrade')}>
						Switch back to single-user…
					</button>
				</>
			)}
			<button type="button" className="link-button" onClick={() => onChoose('samples')}>
				Load a sample model…
			</button>
		</>
	);
}

function SamplesList({
	samples,
	loadingId,
	error,
	onLoad,
	onCancel,
}: {
	samples: SampleModelSummary[];
	loadingId: string | null;
	error: string | null;
	onLoad: (sampleId: string) => void;
	onCancel: () => void;
}) {
	return (
		<div className="sample-models-list">
			<p className="auth-hint">No file of your own? Try one of these.</p>
			{samples.map((sample) => (
				<button
					key={sample.id}
					type="button"
					className="link-button sample-model-option"
					disabled={loadingId !== null}
					onClick={() => onLoad(sample.id)}
				>
					<span className="sample-model-name">{loadingId === sample.id ? 'Loading…' : sample.name}</span>
					<span className="sample-model-description">{sample.description}</span>
				</button>
			))}
			<div className="auth-form-actions">
				<button type="button" className="link-button" disabled={loadingId !== null} onClick={onCancel}>
					Cancel
				</button>
			</div>
			{error && <div className="job-error">{error}</div>}
		</div>
	);
}

function DowngradePanel({
	busy,
	error,
	onConfirm,
	onCancel,
}: {
	busy: boolean;
	error: string | null;
	onConfirm: () => void;
	onCancel: () => void;
}) {
	return (
		<div className="auth-form">
			<p className="auth-hint">
				This deletes every account (usernames and passwords) and merges everyone&rsquo;s printers and job history into one shared,
				login-free setup. Nothing is lost, but accounts and who-owned-what can&rsquo;t be split apart again afterward.
			</p>
			<div className="auth-form-actions">
				<button type="button" className="danger-button" disabled={busy} onClick={onConfirm}>
					{busy ? 'Merging…' : 'Yes, switch back to single-user'}
				</button>
				<button type="button" className="link-button" disabled={busy} onClick={onCancel}>
					Cancel
				</button>
			</div>
			{error && <div className="job-error">{error}</div>}
		</div>
	);
}

function CredentialsForm({
	mode,
	username,
	password,
	busy,
	error,
	onUsername,
	onPassword,
	onSubmit,
	onCancel,
}: {
	mode: 'switch' | 'add';
	username: string;
	password: string;
	busy: boolean;
	error: string | null;
	onUsername: (value: string) => void;
	onPassword: (value: string) => void;
	onSubmit: (e: React.FormEvent) => void;
	onCancel: () => void;
}) {
	return (
		<form className="auth-form" onSubmit={onSubmit}>
			{mode === 'switch' && (
				<p className="auth-hint">This can&rsquo;t be undone -- your existing printers and job history stay attached to this account.</p>
			)}
			<label>
				Username
				<input value={username} onChange={(e) => onUsername(e.target.value)} autoFocus />
			</label>
			<label>
				Password
				<input type="password" value={password} onChange={(e) => onPassword(e.target.value)} />
			</label>
			<div className="auth-form-actions">
				<button type="submit" disabled={busy || !username || !password}>
					{busy ? 'Saving…' : mode === 'switch' ? 'Switch to multi-user' : 'Create user'}
				</button>
				<button type="button" className="link-button" disabled={busy} onClick={onCancel}>
					Cancel
				</button>
			</div>
			{error && <div className="job-error">{error}</div>}
		</form>
	);
}
