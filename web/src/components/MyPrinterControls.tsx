import { useState } from 'react';
import { readMyPrinter } from '../api';
import type { ResinState } from '../hooks/useResin';
import { formFromPrinter, MY_PRINTERS } from '../resinSettings';
import type { MyResinPrinterRequest } from '../types';
import MyPrinterForm from './MyPrinterForm';

// Under the printer's facts: make a printer of your own from this one (or from nothing), and change or delete one of yours.
export default function MyPrinterControls({ r }: { r: ResinState }) {
	const { printer, printers, formats, saveMyPrinter, removeMyPrinter } = r;
	const [open, setOpen] = useState<{ initial: MyResinPrinterRequest; editing: string | null } | null>(null);
	const [error, setError] = useState<string | null>(null);
	const mine = printer?.vendor === MY_PRINTERS;

	const fail = (err: Error) => setError(err.message);
	const edit = () => {
		if (!printer) return;
		setError(null);
		readMyPrinter(printer.name)
			.then((initial) => setOpen({ initial, editing: printer.name }))
			.catch(fail);
	};

	return (
		<div className="my-printer">
			{!open && (
				<div className="my-printer-links">
					<button
						type="button"
						className="link-button"
						disabled={formats.length === 0}
						onClick={() => setOpen({ initial: formFromPrinter(printer, formats), editing: null })}
					>
						{printer ? 'Copy as a custom printer…' : 'My printer is not listed…'}
					</button>
					{mine && (
						<>
							<button type="button" className="link-button" onClick={edit}>
								Edit my printer…
							</button>
							<button type="button" className="link-button danger-text" onClick={() => removeMyPrinter().catch(fail)}>
								Delete my printer
							</button>
						</>
					)}
				</div>
			)}
			{error && <div className="job-error">{error}</div>}
			{open && (
				<MyPrinterForm
					key={open.editing ?? 'new'}
					initial={open.initial}
					editing={open.editing}
					printers={printers}
					formats={formats}
					onSave={saveMyPrinter}
					onClose={() => setOpen(null)}
				/>
			)}
		</div>
	);
}
