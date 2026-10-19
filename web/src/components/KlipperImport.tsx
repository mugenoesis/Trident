import { useState } from 'react';
import { importFromKlipper } from '../api';
import { filledIn, sourceRows } from '../klipperImport';
import type { KlipperImportResult } from '../types';

interface KlipperImportProps {
	// Called with what a successful read gave, for the dialog to fill its fields from.
	onImported: (result: KlipperImportResult) => void;
}

const message = (err: Error) => err.message.replace(/^\d{3}\s+/, '');

/** What was read from the printer: a line that says so, what to check, and where each value came from. */
function Result({ result }: { result: KlipperImportResult }) {
	const { hostname, version } = result.klipper;
	return (
		<>
			<div className="klipper-ok" role="status">
				<strong>Read “{hostname ?? result.form.name}”</strong>
				{version ? ` (Klipper ${version})` : ''}. Filled in below: {filledIn(result)}. Look over everything marked{' '}
				<span className="field-tag" data-tag="check">
					check
				</span>{' '}
				before you save.
			</div>
			{result.notes.length > 0 && (
				<div className="klipper-warn">
					<strong>Worth checking</strong>
					<ul className="klipper-notes">
						{result.notes.map((note) => (
							<li key={note}>{note}</li>
						))}
					</ul>
				</div>
			)}
			<details open className="klipper-sources">
				<summary>Where each value was read</summary>
				<table>
					<tbody>
						{sourceRows(result).map((row) => (
							<tr key={row.label}>
								<td>{row.label}</td>
								<td>{row.value}</td>
								<td>{row.source}</td>
							</tr>
						))}
					</tbody>
				</table>
			</details>
		</>
	);
}

/**
 * "Read it from a Klipper printer": the printer's address (and an API key if its Moonraker wants one), and a button that reads its own
 * config and hands the New printer form it makes to the dialog. Nothing is saved, and nothing on the printer is changed.
 */
export default function KlipperImport({ onImported }: KlipperImportProps) {
	const [address, setAddress] = useState('');
	const [apiKey, setApiKey] = useState('');
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [shown, setShown] = useState<KlipperImportResult | null>(null);

	const read = () => {
		setBusy(true);
		setError(null);
		setShown(null);
		importFromKlipper(address.trim(), apiKey.trim())
			.then((result) => {
				setShown(result);
				onImported(result);
			})
			.catch((err: Error) => setError(message(err)))
			.finally(() => setBusy(false));
	};

	return (
		<div className="klipper-import">
			<h3 className="material-section">Read it from a Klipper printer</h3>
			{!shown && (
				<p className="auth-hint">
					If the printer runs Klipper, Trident can read its own config and fill this form in. Nothing on the printer is changed, and nothing
					is saved until you press Save printer.
				</p>
			)}
			<div className="klipper-row">
				<label>
					Printer address
					<input type="text" value={address} placeholder="http://192.168.1.50" onChange={(e) => setAddress(e.target.value)} />
				</label>
				<label className="klipper-key">
					<span>
						API key <span className="auth-hint">(only if Moonraker asks for one)</span>
					</span>
					<input type="password" value={apiKey} autoComplete="off" onChange={(e) => setApiKey(e.target.value)} />
				</label>
				<button type="button" className="preview-button" disabled={busy || address.trim() === ''} onClick={read}>
					{busy ? 'Reading…' : shown ? 'Read again' : 'Read printer’s settings'}
				</button>
			</div>
			{error && (
				<p className="banner-error" role="alert">
					{error}
				</p>
			)}
			{shown && <Result result={shown} />}
		</div>
	);
}
