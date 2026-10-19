import { useCallback, useEffect, useState } from 'react';
import { getPrinterStatus } from '../api';
import type { PrinterStatus } from '../types';

/** How often a printer's state is asked for while its card is on screen. */
const POLL_MS = 3000;

interface Polled {
	status: PrinterStatus | null;
	/** Why the printer could not be read (off, wrong address…), or null. */
	error: string | null;
	loaded: boolean;
}

/** A saved Klipper printer's live state, asked for now and every few seconds while the component using it is mounted. */
export function usePrinterStatus(printerId: string): Polled & { refresh: () => void } {
	const [polled, setPolled] = useState<Polled>({ status: null, error: null, loaded: false });
	const [nonce, setNonce] = useState(0);
	// asking again at once (after pausing, say) is starting the polling afresh
	const refresh = useCallback(() => setNonce((n) => n + 1), []);

	// biome-ignore lint/correctness/useExhaustiveDependencies: `nonce` restarts the polling when refresh is called
	useEffect(() => {
		let alive = true;
		let timer: ReturnType<typeof setTimeout> | undefined;
		const ask = () => {
			getPrinterStatus(printerId)
				.then((status) => alive && setPolled({ status, error: null, loaded: true }))
				.catch((err: Error) => alive && setPolled({ status: null, error: err.message.replace(/^\d{3}\s+/, ''), loaded: true }))
				.finally(() => {
					if (alive) timer = setTimeout(ask, POLL_MS);
				});
		};
		ask();
		return () => {
			alive = false;
			if (timer) clearTimeout(timer);
		};
	}, [printerId, nonce]);

	return { ...polled, refresh };
}
