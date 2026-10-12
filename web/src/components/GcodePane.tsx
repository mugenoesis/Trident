import { filamentGramsOf } from '../appHelpers';
import type { AppCtx } from '../hooks/useAppController';
import GcodeViewer from './GcodeViewer';
import SendToPrinterControl from './SendToPrinterControl';

// The sliced G-code preview, with the button to send it to the printer.
export default function GcodePane({ c, jobId }: { c: AppCtx; jobId: string }) {
	const { currentJob, history, viewedJobBeltTransform, backToModelView, selectedPrinter, handleSendToPrinter } = c;
	return (
		<>
			<GcodeViewer
				jobId={jobId}
				filamentUsedGrams={filamentGramsOf([currentJob, ...history].find((j) => j?.id === jobId) ?? null)}
				beltTransform={viewedJobBeltTransform}
				onBackToModel={backToModelView}
			/>
			{selectedPrinter?.print_host && (
				<SendToPrinterControl key={jobId} printer={selectedPrinter} jobId={jobId} onSend={handleSendToPrinter} />
			)}
		</>
	);
}
