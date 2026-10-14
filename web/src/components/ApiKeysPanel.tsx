import { useCallback, useEffect, useState } from 'react';
import { createApiKey, listApiKeys, revokeApiKey } from '../api';
import { accessChoice, accessNote, keyDetail, SCOPES } from '../apiKeyText';
import type { ApiKeyCreated, ApiKeyInfo, ApiKeyScope } from '../types';

// The settings menu's "API keys…": keys another program (Holecraft, a script) uses to talk to this Trident without
// a login. A key is shown once, when it is made; only a hash is kept (api/app/userstore.py).
export default function ApiKeysPanel({ onBack }: { onBack: () => void }) {
	const [keys, setKeys] = useState<ApiKeyInfo[] | null>(null);
	const [created, setCreated] = useState<ApiKeyCreated | null>(null);
	const [error, setError] = useState<string | null>(null);

	const refresh = useCallback(() => {
		listApiKeys()
			.then(setKeys)
			.catch((err: Error) => setError(err.message));
	}, []);
	useEffect(refresh, [refresh]);

	if (created) {
		return (
			<MadeKey
				created={created}
				onDone={() => {
					setCreated(null);
					refresh();
				}}
			/>
		);
	}
	return (
		<>
			<div className="settings-status">API keys</div>
			<p className="auth-hint">A key lets another program use this Trident without logging in. It is shown once, when you make it.</p>
			{keys?.map((key) => (
				<KeyRow key={key.id} info={key} onRevoked={refresh} onError={setError} />
			))}
			<NewKeyForm onCreated={setCreated} onBack={onBack} />
			{error && <div className="job-error">{error}</div>}
		</>
	);
}

function KeyRow({ info, onRevoked, onError }: { info: ApiKeyInfo; onRevoked: () => void; onError: (message: string) => void }) {
	const [sure, setSure] = useState(false);
	const revoke = () => {
		revokeApiKey(info.id)
			.then(onRevoked)
			.catch((err: Error) => onError(err.message));
	};
	return (
		<div className="api-key-row">
			<div>
				<strong>{info.name}</strong>
				<div className="settings-status">{keyDetail(info)}</div>
			</div>
			<button type="button" className="link-button danger-text" onClick={sure ? revoke : () => setSure(true)} onBlur={() => setSure(false)}>
				{sure ? 'Really revoke?' : 'Revoke'}
			</button>
		</div>
	);
}

function NewKeyForm({ onCreated, onBack }: { onCreated: (key: ApiKeyCreated) => void; onBack: () => void }) {
	const [name, setName] = useState('');
	const [scope, setScope] = useState<ApiKeyScope>('upload');
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const submit = (e: React.FormEvent) => {
		e.preventDefault();
		setBusy(true);
		setError(null);
		createApiKey(name.trim(), scope)
			.then(onCreated)
			.catch((err: Error) => setError(err.message))
			.finally(() => setBusy(false));
	};
	return (
		<form className="auth-form" onSubmit={submit}>
			<label>
				Name
				<input value={name} maxLength={60} placeholder="Holecraft" onChange={(e) => setName(e.target.value)} />
			</label>
			<label>
				Access
				<select value={scope} onChange={(e) => setScope(e.target.value as ApiKeyScope)}>
					{SCOPES.map((s) => (
						<option key={s} value={s}>
							{accessChoice(s)}
						</option>
					))}
				</select>
			</label>
			<div className="auth-form-actions">
				<button type="submit" disabled={busy || !name.trim()}>
					{busy ? 'Making…' : 'Make key'}
				</button>
				<button type="button" className="link-button" onClick={onBack}>
					Back
				</button>
			</div>
			{error && <div className="job-error">{error}</div>}
		</form>
	);
}

function MadeKey({ created, onDone }: { created: ApiKeyCreated; onDone: () => void }) {
	const [copied, setCopied] = useState<'yes' | 'no' | null>(null);
	// The clipboard is only there on https or localhost, and this is often a plain http address on a home network:
	// when it is not, say so and leave the key selected to copy by hand.
	const copy = () => {
		navigator.clipboard
			?.writeText(created.key)
			.then(() => setCopied('yes'))
			.catch(() => setCopied('no'));
		if (!navigator.clipboard) setCopied('no');
	};
	return (
		<>
			<div className="settings-status">API key made: {created.name}</div>
			<p className="auth-hint">
				<strong>Copy it now.</strong> It will not be shown again. Paste it into Holecraft (Export, Send to Trident).
			</p>
			<input
				readOnly
				value={created.key}
				className="api-key-secret"
				aria-label="The new API key"
				onFocus={(e) => e.currentTarget.select()}
			/>
			<div className="auth-form-actions">
				<button type="button" onClick={copy}>
					{copied === 'yes' ? 'Copied' : 'Copy'}
				</button>
				<button type="button" className="link-button" onClick={onDone}>
					Done
				</button>
			</div>
			{copied === 'no' && <div className="settings-status">Your browser would not copy it: select the key above and press Ctrl+C.</div>}
			<div className="settings-status">{accessNote(created.scope)}</div>
		</>
	);
}
