import { useCallback } from 'react';
import { createPrinter, deletePrinter, updatePrinter } from '../api';
import type { PrinterConnection, PrinterUpdateRequest } from '../types';
import type { AppState, MainAppProps } from './useAppState';

export function usePrinterCrud(c: AppState & Pick<MainAppProps, never>) {
	const { vendor, printerName, processName, filamentSlots, bedSize, setPrinters, setSelectedPrinterId } = c;

	const handleSavePrinter = useCallback(
		(name: string, connection: PrinterConnection) => {
			return createPrinter({
				name,
				vendor,
				machine_profile: printerName,
				process_profile: processName,
				filament_profiles: filamentSlots.map((s) => s.profile),
				filament_colors: filamentSlots.map((s) => s.color),
				bed_width: bedSize?.width ?? null,
				bed_depth: bedSize?.depth ?? null,
				bed_height: bedSize?.height ?? null,
				...connection,
			}).then((printer) => {
				setPrinters((prev) => [...prev, printer]);
				setSelectedPrinterId(printer.id);
			});
		},
		[vendor, printerName, processName, filamentSlots, bedSize, setPrinters, setSelectedPrinterId],
	);

	const handleUpdatePrinter = useCallback(
		(id: string, body: PrinterUpdateRequest) => {
			return updatePrinter(id, body).then((printer) => {
				setPrinters((prev) => prev.map((p) => (p.id === id ? printer : p)));
			});
		},
		[setPrinters],
	);

	const handleDeletePrinter = useCallback(
		(id: string) => {
			deletePrinter(id)
				.then(() => {
					setPrinters((prev) => prev.filter((p) => p.id !== id));
					setSelectedPrinterId((prev) => (prev === id ? null : prev));
				})
				.catch((err: Error) => alert(`Failed to delete printer: ${err.message}`));
		},
		[setSelectedPrinterId, setPrinters],
	);
	return { handleSavePrinter, handleUpdatePrinter, handleDeletePrinter };
}
