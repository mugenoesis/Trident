import { useState } from 'react';
import { runBambuSession } from '../api';

/** EXPERIMENT: gives the pasted sign-in to Bambu's plug-in and shows each step it reports (no token, serial number or access code is ever in it). */
export default function BambuSessionTest() {
	const [busy, setBusy] = useState(false);
	const [steps, setSteps] = useState<{ step: string; value: unknown }[] | null>(null);
	const [problem, setProblem] = useState<string | null>(null);

	const run = () => {
		setBusy(true);
		setProblem(null);
		runBambuSession()
			.then((r) => setSteps(r.steps))
			.catch((err: Error) => setProblem(err.message.replace(/^\d{3}\s+/, '')))
			.finally(() => setBusy(false));
	};

	return (
		<>
			<button type="button" className="preview-button" disabled={busy} onClick={run}>
				{busy ? 'Asking the plug-in…' : 'Connect the plug-in to this sign-in'}
			</button>
			{problem && <p className="banner-error">{problem}</p>}
			{steps && <pre className="printer-raw">{steps.map((s) => `${s.step}: ${JSON.stringify(s.value)}`).join('\n')}</pre>}
		</>
	);
}
