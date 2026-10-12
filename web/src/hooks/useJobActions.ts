import { useCallback } from 'react';
import { deleteJob, listJobs, sendToPrinter } from '../api';
import type { AppState, MainAppProps } from './useAppState';

export function useJobActions(c: AppState & Pick<MainAppProps, never>) {
	const { selectedPrinterId, setHistory, setCurrentJob, setViewedJobId, setViewMode } = c;

	const handleSendToPrinter = useCallback(
		(jobId: string, startPrint: boolean) => {
			if (!selectedPrinterId) return Promise.reject(new Error('No printer selected'));
			return sendToPrinter(selectedPrinterId, jobId, startPrint);
		},
		[selectedPrinterId],
	);

	const handleDeleteJob = useCallback(
		(jobId: string) => {
			deleteJob(jobId)
				.then(() => {
					listJobs()
						.then(setHistory)
						.catch(() => {});
					setCurrentJob((prev) => (prev?.id === jobId ? null : prev));
					setViewedJobId((prev) => {
						if (prev !== jobId) return prev;
						setViewMode('model');
						return null;
					});
				})
				.catch((err: Error) => alert(`Failed to delete job: ${err.message}`));
		},
		[setCurrentJob, setViewMode, setHistory, setViewedJobId],
	);
	return { handleSendToPrinter, handleDeleteJob };
}
