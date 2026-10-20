import { useEffect, useState } from 'react';
import { listPrinters } from '../api';
import { livePrinters } from '../printerStatus';
import type { PrinterRecord } from '../types';
import PrinterCard from './PrinterCard';

/**
 * "Your printers": a card for each saved printer that has a Klipper (Moonraker) address, with what it is doing now, kept up to date while
 * the page is open (and not asked for once it is closed). Pause, resume and cancel are all it can do to a printer.
 */
function PrintersPanel({ onClose }: { onClose: () => void }) {
	const [printers, setPrinters] = useState<PrinterRecord[] | null>(null);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		listPrinters()
			.then((list) => setPrinters(livePrinters(list)))
			.catch((err: Error) => setError(err.message));
	}, []);

	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			if (e.key === 'Escape' && !document.querySelector('[role="alertdialog"]')) onClose();
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	}, [onClose]);

	return (
		<div className="printers-overlay">
			<div className="printers-panel" role="dialog" aria-modal="true" aria-label="Your printers">
				<div className="printers-head">
					<h2>Your printers</h2>
					<button type="button" className="link-button" onClick={onClose}>
						Close ✕
					</button>
				</div>
				{error && <p className="banner-error">{error}</p>}
				{!printers && !error && <p className="auth-hint">Loading…</p>}
				{printers?.length === 0 && (
					<p className="auth-hint">
						No saved printer has a Klipper (Moonraker) address or a Bambu (LAN mode) connection yet. Save a printer with its connection
						(under Printer settings, Manage saved printers) and it appears here.
					</p>
				)}
				<div className="printers-grid">
					{printers?.map((p) => (
						<PrinterCard key={p.id} printer={p} />
					))}
				</div>
				<p className="auth-hint">
					Only printers saved with a Klipper (Moonraker) or Bambu (LAN mode) connection are shown. Cancelling asks first. Pause, resume and
					cancel are all this page can do to a printer.
				</p>
			</div>
		</div>
	);
}

/** The "Printers" button of the header, and the page it opens. */
export default function PrintersButton() {
	const [open, setOpen] = useState(false);
	return (
		<>
			<button type="button" className="preview-button printers-button" onClick={() => setOpen(true)}>
				Printers
			</button>
			{open && <PrintersPanel onClose={() => setOpen(false)} />}
		</>
	);
}
