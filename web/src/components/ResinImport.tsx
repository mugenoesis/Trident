import { useRef, useState } from 'react';
import type { ResinImportResult } from '../types';

interface ResinImportProps {
	// The printer the settings of the file will be for (empty: any printer).
	printerName: string;
	onImport: (file: File) => Promise<ResinImportResult>;
}

// "Import a resin file…": a Chitubox resin profile (.cfg) or a PrusaSlicer profile (.ini), saved as resins of your own.
export default function ResinImport({ printerName, onImport }: ResinImportProps) {
	const input = useRef<HTMLInputElement>(null);
	const [message, setMessage] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [busy, setBusy] = useState(false);

	const run = (file: File) => {
		setBusy(true);
		setMessage(null);
		setError(null);
		onImport(file)
			.then((result) => {
				const n = result.imported.length;
				const where = printerName ? ` for ${printerName}` : ' for any printer';
				setMessage(`Imported ${n} resin${n === 1 ? '' : 's'}${where}.${result.skipped.map((s) => ` ${s.reason}.`).join('')}`);
			})
			.catch((err: Error) => setError(err.message.replace(/^\d+ /, '')))
			.finally(() => setBusy(false));
	};

	return (
		<div className="resin-import">
			<button type="button" className="link-button" disabled={busy} onClick={() => input.current?.click()}>
				Import a resin file…
			</button>
			<input
				ref={input}
				type="file"
				accept=".cfg,.ini"
				hidden
				onChange={(e) => {
					const file = e.target.files?.[0];
					e.target.value = '';
					if (file) run(file);
				}}
			/>
			{message && <div className="job-hint resin-hint">{message}</div>}
			{error && <div className="job-error">{error}</div>}
		</div>
	);
}
