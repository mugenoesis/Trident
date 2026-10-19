import { formatDuration } from './resinSettings';
import type { PrinterRecord, PrinterStatus } from './types';

const LABELS: Record<string, string> = {
	printing: 'Printing',
	paused: 'Paused',
	complete: 'Finished',
	standby: 'Idle',
	cancelled: 'Cancelled',
	error: 'Error',
	shutdown: 'Klipper has shut down',
	startup: 'Starting up',
	offline: 'Offline',
};

/** What a printer's state is called on its card. */
export function stateLabel(state: string): string {
	return LABELS[state] ?? state;
}

export type StateTone = 'printing' | 'paused' | 'done' | 'error' | 'off';

/** The colour family of a state's chip: green while printing, amber when paused, blue when done, red when something is wrong, grey otherwise. */
export function stateTone(state: string): StateTone {
	if (state === 'printing') return 'printing';
	if (state === 'paused') return 'paused';
	if (state === 'complete') return 'done';
	if (state === 'error' || state === 'shutdown') return 'error';
	return 'off';
}

/** The saved printers a live page can show: the ones with a Klipper (Moonraker) address. */
export function klipperPrinters(printers: PrinterRecord[]): PrinterRecord[] {
	return printers.filter((p) => p.host_type === 'moonraker' && !!p.print_host);
}

/** "42%" for a progress between 0 and 1, or null when there is none. */
export function percentText(progress: number | null): string | null {
	return progress === null ? null : `${Math.round(progress * 100)}%`;
}

/** "layer 12 of 80", or null without layer information. */
export function layerText(status: PrinterStatus): string | null {
	return status.layer ? `layer ${status.layer.current} of ${status.layer.total}` : null;
}

/** The time so far and, for a print under way, the time left: "1 h 12 min so far · about 1 h 38 min left". */
export function timeText(status: PrinterStatus): string {
	const parts: string[] = [];
	if (status.elapsed_s !== null && status.elapsed_s > 0)
		parts.push(status.state === 'complete' ? formatDuration(status.elapsed_s) : `${formatDuration(status.elapsed_s)} so far`);
	if (status.remaining_s !== null) parts.push(`about ${formatDuration(status.remaining_s)} left`);
	return parts.join(' · ');
}

/** Whether a webcam picture is worth fetching: while something is printing or paused. */
export function showsCamera(status: PrinterStatus): boolean {
	return status.state === 'printing' || status.state === 'paused';
}
