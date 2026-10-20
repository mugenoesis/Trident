import { useEffect, useState } from 'react';
import { type BambuCloudStatus, getBambuCloud, getBambuSignInUrl, installBambuPlugin, pasteBambuAddress } from '../api';

/** What Bambu's redirect carried, by field name and length (the server never sends back a value). */
function CallbackResult({ callback }: { callback: NonNullable<BambuCloudStatus['callback']> }) {
	return (
		<p className="auth-hint">
			Bambu sent the browser back with:{' '}
			{callback.fields.length ? callback.fields.map((f) => `${f.name} (${f.length} characters)`).join(', ') : 'no fields'}
			{callback.extra_path_lengths.length > 0 && `; and ${callback.extra_path_lengths.length} extra path part(s)`}.
		</p>
	);
}

/**
 * EXPERIMENT: signing in to Bambu Cloud through Bambu's own network plug-in, so a printer can stay in cloud mode. Step 1 downloads the plug-in
 * from Bambu (on request); step 2 opens Bambu's own sign-in page in this browser, which sends it back to Trident when you are signed in.
 * Shown only when the server has the experiment switched on.
 */
export default function BambuCloudTest() {
	const [status, setStatus] = useState<BambuCloudStatus | null>(null);
	const [busy, setBusy] = useState(false);
	const [problem, setProblem] = useState<string | null>(null);
	const [waiting, setWaiting] = useState(false);

	useEffect(() => {
		let alive = true;
		const ask = () =>
			getBambuCloud()
				.then((s) => alive && setStatus(s))
				.catch(() => undefined);
		ask();
		const timer = waiting ? setInterval(ask, 2000) : undefined;
		return () => {
			alive = false;
			if (timer) clearInterval(timer);
		};
	}, [waiting]);

	if (!status?.enabled) return null;

	const install = () => {
		setBusy(true);
		setProblem(null);
		installBambuPlugin()
			.then((plugin) => setStatus({ ...status, plugin }))
			.catch((err: Error) => setProblem(err.message.replace(/^\d{3}\s+/, '')))
			.finally(() => setBusy(false));
	};

	const [pasted, setPasted] = useState('');
	const paste = () => {
		setProblem(null);
		pasteBambuAddress(pasted)
			.then((callback) => {
				setStatus({ ...status, callback });
				setPasted('');
			})
			.catch((err: Error) => setProblem(err.message.replace(/^\d{3}\s+/, '')));
	};

	const signIn = (loopback: boolean) => {
		setProblem(null);
		getBambuSignInUrl(window.location.origin, loopback)
			.then(({ url }) => {
				window.open(url, '_blank', 'noopener');
				setWaiting(true);
			})
			.catch((err: Error) => setProblem(err.message.replace(/^\d{3}\s+/, '')));
	};

	return (
		<fieldset className="bambu-cloud-test">
			<legend>Experimental: Bambu Cloud sign-in</legend>
			<p className="auth-hint">
				For a printer that stays in cloud mode. This uses Bambu's own network plug-in, which Trident downloads from Bambu only when you ask.
				You sign in on Bambu's own page in your browser; Trident never sees your password.
			</p>
			{status.plugin?.installed ? (
				<p className="auth-hint">
					Plug-in {status.plugin.version} downloaded (SHA-256 {status.plugin.sha256}).
				</p>
			) : (
				<button type="button" className="preview-button" disabled={busy} onClick={install}>
					{busy ? 'Downloading…' : "Download Bambu's network plug-in"}
				</button>
			)}
			<button type="button" className="preview-button" onClick={() => signIn(false)}>
				Sign in with Bambu (sends the browser back here)
			</button>
			<button type="button" className="preview-button" onClick={() => signIn(true)}>
				Sign in with Bambu (the link Orca uses: sends the browser to localhost)
			</button>
			<label>
				After that one, copy the address the browser ends up on and paste it here (only its field names are kept)
				<input value={pasted} onChange={(e) => setPasted(e.target.value)} placeholder="http://localhost:41999/…" autoComplete="off" />
			</label>
			<button type="button" className="preview-button" disabled={!pasted} onClick={paste}>
				Check that address
			</button>
			{problem && <p className="banner-error">{problem}</p>}
			{status.callback && <CallbackResult callback={status.callback} />}
		</fieldset>
	);
}
