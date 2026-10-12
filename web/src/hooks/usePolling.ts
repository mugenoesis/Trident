import { useEffect } from 'react';
import { getJob, listJobs } from '../api';
import { ACTIVE_STATUSES, POLL_INTERVAL_MS } from '../appHelpers';
import type { AppState, MainAppProps } from './useAppState';
import type { useViewedJob } from './useViewedJob';

export function usePolling(c: AppState & Pick<MainAppProps, never> & ReturnType<typeof useViewedJob>) {
	const { currentJob, pollRef, setCurrentJob, setSlicing, setHistory, viewJobGcode } = c;

	// biome-ignore lint/correctness/useExhaustiveDependencies: restarts only when the job changes or finishes; the rest of the job is not a trigger
	useEffect(() => {
		if (!currentJob || !ACTIVE_STATUSES.includes(currentJob.status)) {
			if (pollRef.current) clearInterval(pollRef.current);
			return;
		}
		pollRef.current = setInterval(() => {
			getJob(currentJob.id)
				.then((job) => {
					setCurrentJob(job);
					if (!ACTIVE_STATUSES.includes(job.status)) {
						setSlicing(false);
						listJobs()
							.then(setHistory)
							.catch(() => {});
						if (job.status === 'succeeded') viewJobGcode(job.id);
					}
				})
				.catch(() => {
					if (pollRef.current) clearInterval(pollRef.current);
				});
		}, POLL_INTERVAL_MS);
		return () => {
			if (pollRef.current) clearInterval(pollRef.current);
		};
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [currentJob?.id, currentJob?.status]);
}
