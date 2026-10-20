import { useEffect, useState } from 'react';
import { controlPrint, listPrinterWebcams } from '../api';
import { usePrinterStatus } from '../hooks/usePrinterStatus';
import { layerText, percentText, showsCamera, stateLabel, stateTone, timeText } from '../printerStatus';
import type { PrintAction, PrinterCamera, PrinterRecord, PrinterStatus } from '../types';
import PrinterCam from './PrinterCam';
import RawStatus from './RawStatus';

/** "Nozzle 214.8° / 215°" tiles: a heater that is heating is outlined. */
function Temperatures({ status }: { status: PrinterStatus }) {
	return (
		<div className="printer-temps">
			{status.temperatures.map((t) => (
				<div key={t.name} className={t.target ? 'printer-temp hot' : 'printer-temp'}>
					<small>{t.name}</small>
					<strong>{t.current}°</strong>
					{t.target !== null && <span> / {t.target}°</span>}
				</div>
			))}
		</div>
	);
}

/** "Cancel the print on Voron?": cancelling cannot be undone, so it is asked twice. */
function ConfirmCancel({
	printer,
	status,
	busy,
	onKeep,
	onCancel,
}: {
	printer: string;
	status: PrinterStatus;
	busy: boolean;
	onKeep: () => void;
	onCancel: () => void;
}) {
	return (
		<div className="printer-confirm-backdrop">
			<div className="printer-confirm" role="alertdialog" aria-label={`Cancel the print on ${printer}?`} aria-modal="true">
				<h3>Cancel the print on {printer}?</h3>
				<p className="auth-hint">
					{status.file} is {percentText(status.progress) ?? 'under way'} done. Cancelling stops it for good: it cannot be resumed.
				</p>
				<div className="printer-actions">
					<button type="button" className="preview-button" onClick={onKeep}>
						Keep printing
					</button>
					<button type="button" className="preview-button printer-danger" disabled={busy} onClick={onCancel}>
						Cancel the print
					</button>
				</div>
			</div>
		</div>
	);
}

/** The webcams of a printer while it prints or is paused (asked for once, when it first is). */
function useCameras(printerId: string, wanted: boolean): PrinterCamera[] {
	const [cameras, setCameras] = useState<PrinterCamera[] | null>(null);
	useEffect(() => {
		if (!wanted || cameras !== null) return;
		let alive = true;
		listPrinterWebcams(printerId)
			.then((list) => alive && setCameras(list))
			.catch(() => alive && setCameras([]));
		return () => {
			alive = false;
		};
	}, [printerId, wanted, cameras]);
	return cameras ?? [];
}

/** The pause, resume and cancel buttons a print allows, with what goes wrong on the way. */
function Controls({ printer, status, onDone }: { printer: PrinterRecord; status: PrinterStatus; onDone: () => void }) {
	const [busy, setBusy] = useState(false);
	const [asking, setAsking] = useState(false);
	const [problem, setProblem] = useState<string | null>(null);

	const run = (action: PrintAction) => {
		setBusy(true);
		setProblem(null);
		controlPrint(printer.id, action)
			.then(onDone)
			.catch((err: Error) => setProblem(err.message.replace(/^\d{3}\s+/, '')))
			.finally(() => {
				setBusy(false);
				setAsking(false);
			});
	};

	return (
		<>
			{problem && (
				<p className="banner-error" role="alert">
					{problem}
				</p>
			)}
			<div className="printer-actions">
				{status.can.pause && (
					<button type="button" className="preview-button" disabled={busy} onClick={() => run('pause')}>
						Pause
					</button>
				)}
				{status.can.resume && (
					<button type="button" className="preview-button" disabled={busy} onClick={() => run('resume')}>
						Resume
					</button>
				)}
				{status.can.cancel && (
					<button type="button" className="preview-button printer-danger" disabled={busy} onClick={() => setAsking(true)}>
						Cancel print…
					</button>
				)}
			</div>
			{asking && (
				<ConfirmCancel printer={printer.name} status={status} busy={busy} onKeep={() => setAsking(false)} onCancel={() => run('cancel')} />
			)}
		</>
	);
}

/** One printer: its state, the print under way, the temperatures, a webcam and the buttons that go with them (or why it cannot be reached). */
export default function PrinterCard({ printer }: { printer: PrinterRecord }) {
	const { status, error, loaded, refresh } = usePrinterStatus(printer.id);
	const cameras = useCameras(printer.id, !!status && showsCamera(status));
	const state = status ? status.state : 'offline';

	return (
		<article className="printer-card" aria-label={printer.name}>
			<div className="printer-top">
				<span className="printer-name">{printer.name}</span>
				{loaded && <span className={`printer-chip ${stateTone(state)}`}>{stateLabel(state)}</span>}
			</div>
			{!loaded && <p className="auth-hint">Asking the printer…</p>}
			{error && (
				<>
					<p className="printer-off">{error}. It may be off; trying again every few seconds.</p>
					<p className="auth-hint">{printer.print_host}</p>
				</>
			)}
			{status && (
				<>
					{status.state_message && <p className="printer-message">{status.state_message}</p>}
					{status.file && <div className="printer-file">{status.file}</div>}
					{status.progress !== null && (
						<>
							<div
								className="printer-bar"
								role="progressbar"
								aria-valuemin={0}
								aria-valuemax={100}
								aria-valuenow={Math.round(status.progress * 100)}
							>
								<div style={{ width: `${Math.round(status.progress * 100)}%` }} />
							</div>
							<div className="printer-meta">
								<span>
									<strong>{percentText(status.progress)}</strong>
									{layerText(status) && ` · ${layerText(status)}`}
								</span>
								<span>{timeText(status)}</span>
							</div>
						</>
					)}
					<Temperatures status={status} />
					{showsCamera(status) && <PrinterCam printerId={printer.id} cameras={cameras} />}
					<Controls printer={printer} status={status} onDone={refresh} />
					{printer.host_type === 'bambu' && <RawStatus printerId={printer.id} />}
				</>
			)}
		</article>
	);
}
