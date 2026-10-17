import { useCallback } from 'react';
import { createPrinter, deletePrinter, updatePrinter } from '../api';
import type { PrinterConnection, PrinterCreateRequest, PrinterUpdateRequest } from '../types';
import type { AppState, MainAppProps } from './useAppState';
import type { ResinState } from './useResin';

// A resin printer is not sent G-code over the network, so it has no connection.
const NO_CONNECTION: PrinterConnection = {
	host_type: null,
	print_host: null,
	printhost_apikey: null,
	printhost_user: null,
	printhost_password: null,
};

function resinPrinterRequest(name: string, resin: ResinState): PrinterCreateRequest {
	return {
		technology: 'resin',
		name,
		vendor: resin.printer?.vendor ?? '',
		machine_profile: resin.printerName,
		process_profile: '',
		filament_profiles: resin.resinName ? [resin.resinName] : [],
		filament_colors: [],
		resin_settings: resin.settingsToSave(),
		bed_width: null,
		bed_depth: null,
		bed_height: null,
		...NO_CONNECTION,
	};
}

export function usePrinterCrud(c: AppState & Pick<MainAppProps, never> & { resin: ResinState }) {
	const { vendor, printerName, processName, filamentSlots, bedSize, setPrinters, setSelectedPrinterId, resin } = c;

	const handleSavePrinter = useCallback(
		(name: string, connection: PrinterConnection) => {
			const request: PrinterCreateRequest =
				resin.technology === 'resin'
					? resinPrinterRequest(name, resin)
					: {
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
						};
			return createPrinter(request).then((printer) => {
				setPrinters((prev) => [...prev, printer]);
				setSelectedPrinterId(printer.id);
			});
		},
		[resin, vendor, printerName, processName, filamentSlots, bedSize, setPrinters, setSelectedPrinterId],
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
