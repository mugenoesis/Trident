import { useEffect, useState } from 'react';
import { getPrinterRawStatus } from '../api';

/**
 * "Raw status": what a Bambu printer reports, as it sends it, without its serial number, address or code. Bambu's protocol is documented by its
 * users, not by Bambu, so this is how to find out what a printer says that the card does not show (and what to paste when asking about it).
 */
export default function RawStatus({ printerId }: { printerId: string }) {
	const [open, setOpen] = useState(false);
	const [text, setText] = useState<string | null>(null);
	const [problem, setProblem] = useState<string | null>(null);

	useEffect(() => {
		if (!open) return;
		let alive = true;
		getPrinterRawStatus(printerId)
			.then((raw) => {
				if (!alive) return;
				setText(JSON.stringify(raw.report, null, 2));
				setProblem(null);
			})
			.catch((err: Error) => alive && setProblem(err.message.replace(/^\d{3}\s+/, '')));
		return () => {
			alive = false;
		};
	}, [open, printerId]);

	return (
		<details className="printer-raw-box" onToggle={(e) => setOpen(e.currentTarget.open)}>
			<summary>Raw status</summary>
			{problem && <p className="banner-error">{problem}</p>}
			{text && <pre className="printer-raw">{text}</pre>}
		</details>
	);
}
