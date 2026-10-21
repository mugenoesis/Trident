import { useState } from 'react';
import type { BambuAccount, BambuAccountPrinter, BambuImportResult } from '../api';
import { useBambuPicker, useBambuSignIn } from '../hooks/useBambuAccount';

const stateText = (online: boolean | null) => (online === null ? '' : online ? '● online' : '○ offline');

/** The sign-in: one button that opens Bambu's page, and a box that takes the address that tab ends on and connects at once. */
function SignIn({
	busy,
	link,
	onSignIn,
	onConnect,
}: {
	busy: string | null;
	link: string | null;
	onSignIn: () => void;
	onConnect: (address: string) => void;
}) {
	return (
		<div className="bambu-account-step">
			<button type="button" className="preview-button" disabled={busy !== null} onClick={onSignIn}>
				Sign in with Bambu
			</button>
			{link && (
				<a href={link} target="_blank" rel="noopener noreferrer">
					Open Bambu's sign-in page
				</a>
			)}
			<label>
				When you are signed in, that tab ends on a page that cannot load. Copy its address and paste it here.
				<input
					placeholder="Paste the address here"
					autoComplete="off"
					disabled={busy !== null}
					onPaste={(e) => {
						e.preventDefault();
						onConnect(e.clipboardData.getData('text'));
					}}
				/>
			</label>
		</div>
	);
}

/** One printer of the account: whether to add it, its state and the address it was found at (or a note that Trident has no profile for it). */
function PrinterRow({
	printer,
	checked,
	ip,
	onToggle,
	onIp,
}: {
	printer: BambuAccountPrinter;
	checked: boolean;
	ip: string;
	onToggle: () => void;
	onIp: (value: string) => void;
}) {
	const label = printer.name ?? printer.model;
	return (
		<li className="bambu-account-row">
			<label className="checkbox-label">
				<input type="checkbox" checked={checked} disabled={!printer.supported} onChange={onToggle} />
				<span>
					{label}
					{printer.name && ` · ${printer.model}`} <small>{stateText(printer.online)}</small>
				</span>
			</label>
			{printer.supported ? (
				<input
					aria-label={`IP address of ${label}`}
					placeholder="IP address"
					inputMode="decimal"
					value={ip}
					onChange={(e) => onIp(e.target.value)}
				/>
			) : (
				<small>Trident has no profile for this model</small>
			)}
		</li>
	);
}

/** What adding did: the printers added, and why any was not. */
function Outcome({ outcome }: { outcome: BambuImportResult }) {
	return (
		<div className="auth-hint">
			{outcome.added.length > 0 && <p>✓ Added: {outcome.added.map((a) => a.name).join(', ')}. They are in your saved printers now.</p>}
			{outcome.skipped.map((s) => (
				<p key={s.index}>Skipped one: {s.reason}.</p>
			))}
		</div>
	);
}

/** Shown only while a printer has no address: where it was looked for, and a way to look on another network. */
function SearchAgain({
	missing,
	network,
	busy,
	onSearch,
}: {
	missing: number;
	network: string | null;
	busy: boolean;
	onSearch: (network: string) => void;
}) {
	const [where, setWhere] = useState(network ?? '');
	return (
		<div className="bambu-account-step">
			<p className="auth-hint">
				Could not find {missing} printer{missing === 1 ? '' : 's'}
				{network ? ` on ${network}` : ' (Trident was not opened from an address on your own network)'}. Type the address if you know it, or
				search another network:
			</p>
			<input value={where} onChange={(e) => setWhere(e.target.value)} placeholder="192.168.1.0/24" aria-label="Network to search" />
			<button type="button" className="preview-button" disabled={busy || !where.trim()} onClick={() => onSearch(where.trim())}>
				{busy ? 'Searching…' : 'Search'}
			</button>
		</div>
	);
}

/** The printers of a signed-in account: choose which to add, check the addresses, add them. */
function Picker({ account, onAdded }: { account: BambuAccount; onAdded: () => void }) {
	const picker = useBambuPicker(account, onAdded);
	const count = picker.chosen.size;
	const missing = account.printers.filter((p) => p.supported && !(picker.ips[p.index] ?? '').trim()).length;
	return (
		<div className="bambu-account-step">
			<strong>Signed in as {account.user}</strong>
			<ul className="bambu-account-list">
				{account.printers.map((printer) => (
					<PrinterRow
						key={printer.index}
						printer={printer}
						checked={picker.chosen.has(printer.index)}
						ip={picker.ips[printer.index] ?? ''}
						onToggle={() => picker.toggle(printer.index)}
						onIp={(value) => picker.setIp(printer.index, value)}
					/>
				))}
			</ul>
			{missing > 0 && <SearchAgain missing={missing} network={account.network} busy={picker.searching} onSearch={picker.search} />}
			<button type="button" className="preview-button" disabled={picker.busy || count === 0} onClick={picker.add}>
				{picker.busy ? 'Adding…' : `Add ${count} printer${count === 1 ? '' : 's'}`}
			</button>
			{picker.problem && <p className="banner-error">{picker.problem}</p>}
			{picker.outcome && <Outcome outcome={picker.outcome} />}
		</div>
	);
}

/**
 * EXPERIMENT: add the printers of a Bambu account as saved printers. Shown only when the server has the experiment switched on; sits under
 * "Save current setup as printer…", folded away until it is wanted.
 */
export default function BambuAccountImport({ onAdded }: { onAdded: () => void }) {
	const sign = useBambuSignIn();
	if (!sign.enabled) return null;
	return (
		<details className="job-history bambu-account">
			<summary>Add from Bambu account (experimental)</summary>
			<SignIn busy={sign.busy} link={sign.link} onSignIn={sign.signIn} onConnect={sign.connect} />
			{sign.busy && <p className="auth-hint">{sign.busy}</p>}
			{sign.problem && <p className="banner-error">{sign.problem}</p>}
			{sign.account && !sign.account.signed_in && <p className="banner-error">✗ {sign.account.problem}</p>}
			{sign.account?.signed_in && <Picker key={sign.account.import_id ?? 'list'} account={sign.account} onAdded={onAdded} />}
		</details>
	);
}
