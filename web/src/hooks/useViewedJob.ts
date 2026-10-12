import { useCallback, useEffect } from 'react';
import { getProfileDetail, listProfiles } from '../api';
import { parseBedSize } from '../dimensions';
import type { AppState, MainAppProps } from './useAppState';

export function useViewedJob(c: AppState & Pick<MainAppProps, never>) {
	const { viewMode, viewedJobId, currentJob, history, setViewedJobBeltTransform, setViewedJobId, setViewMode } = c;

	const showGcode = viewMode === 'gcode' && viewedJobId !== null;
	useEffect(() => {
		const job = viewedJobId ? ([currentJob, ...history].find((j) => j?.id === viewedJobId) ?? null) : null;
		if (!job) {
			setViewedJobBeltTransform(null);
			return;
		}
		let cancelled = false;
		listProfiles()
			.then((profiles) => {
				const match = profiles.find((p) => p.kind === 'machine' && p.name === job.printer_profile);
				return match ? getProfileDetail(match.vendor, 'machine', match.name) : null;
			})
			.then((detail) => {
				if (cancelled) return;
				setViewedJobBeltTransform(detail ? (parseBedSize(detail.data)?.beltTransform ?? null) : null);
			})
			.catch(() => {
				if (!cancelled) setViewedJobBeltTransform(null);
			});
		return () => {
			cancelled = true;
		};
	}, [viewedJobId, currentJob, history, setViewedJobBeltTransform]);

	const viewJobGcode = useCallback(
		(jobId: string) => {
			setViewedJobId(jobId);
			setViewMode('gcode');
			window.scrollTo({ top: 0, behavior: 'smooth' });
		},
		[setViewedJobId, setViewMode],
	);

	const backToModelView = useCallback(() => setViewMode('model'), [setViewMode]);
	return { showGcode, viewJobGcode, backToModelView };
}
