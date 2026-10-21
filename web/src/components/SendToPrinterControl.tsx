import { useEffect, useState } from 'react';
import { getBambuCloud } from '../api';
import type { PrinterRecord } from '../types';

interface SendToPrinterControlProps {
	printer: PrinterRecord;
	jobId: string;
	onSend: (jobId: string, startPrint: boolean, useAms: boolean) => Promise<unknown>;
}

// Rendered alongside GcodeViewer (App.tsx), not buried down in JobPanel's
// settings column -- slicing scrolls the page back to the G-code view, so
// anything you'd want to do right after (download, send) needs to live up
// there too, or it's an extra scroll back down every single time.
export default function SendToPrinterControl({ printer, jobId, onSend }: SendToPrinterControlProps) {
	const [startPrint, setStartPrint] = useState(false);
	// A Bambu printer can print from its AMS (the first slot) instead of the spool on its back.
	const [useAms, setUseAms] = useState(false);
	const [busy, setBusy] = useState(false);
	const [result, setResult] = useState<'idle' | 'sent' | 'error'>('idle');
	const [error, setError] = useState<string | null>(null);
	// A Bambu printer saved as monitor only (left in cloud mode) can always be sent the file; it can be told to start only through Bambu's
	// plug-in (an experiment), which the server says it has.
	const monitorOnly = !!printer.monitor_only;
	const [viaPlugin, setViaPlugin] = useState(false);
	useEffect(() => {
		setViaPlugin(false);
		if (!monitorOnly || printer.host_type !== 'bambu') return;
		let current = true;
		getBambuCloud()
			.then((status) => current && setViaPlugin(!!status.can_print))
			.catch(() => {});
		return () => {
			current = false;
		};
	}, [monitorOnly, printer.host_type]);
	const canStart = !monitorOnly || viaPlugin;
	const starting = canStart && startPrint;

	const send = () => {
		setBusy(true);
		setResult('idle');
		setError(null);
		onSend(jobId, starting, useAms)
			.then(() => setResult('sent'))
			.catch((err: Error) => {
				setResult('error');
				setError(err.message);
			})
			.finally(() => setBusy(false));
	};

	return (
		<div className="send-to-printer">
			{canStart && (
				<label className="checkbox-label">
					<input type="checkbox" checked={startPrint} onChange={(e) => setStartPrint(e.target.checked)} />
					Start printing immediately{viaPlugin ? " (experimental: Bambu's plug-in starts it)" : ''}
				</label>
			)}
			{canStart && printer.host_type === 'bambu' && (
				<label className="checkbox-label">
					<input type="checkbox" checked={useAms} onChange={(e) => setUseAms(e.target.checked)} />
					Print from the AMS (its first slot)
				</label>
			)}
			<button type="button" className="preview-button" disabled={busy} onClick={send}>
				{busy ? (starting ? 'Sending and starting…' : 'Sending…') : `Send to ${printer.name}`}
			</button>
			{!canStart && result !== 'sent' && <div className="job-hint">This sends the file only: you start the print on {printer.name}.</div>}
			{result === 'sent' && (
				<div className="job-hint">
					{!canStart || !startPrint ? `Sent to ${printer.name}. Start it from the printer's screen.` : `Sent to ${printer.name}.`}
				</div>
			)}
			{result === 'error' && <div className="job-error">{error}</div>}
		</div>
	);
}
