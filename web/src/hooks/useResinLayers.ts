import { useCallback, useEffect, useRef, useState } from 'react';
import { getLayerPreview, startLayerPreview } from '../api';
import { POLL_INTERVAL_MS } from '../appHelpers';
import type { LayerPreviewStatus } from '../types';

const NONE: LayerPreviewStatus = {
	status: 'none',
	layer_count: null,
	error: null,
	peak_layer: null,
	peak_area_cm2: null,
	peel_warning: false,
	peel_warning_cm2: null,
};

// The server starts the layer images of a resin job itself, a moment after the job succeeds; "none" that long after is an old job.
const POLLS_BEFORE_GIVING_UP = 5;

// The layer images of a resin job, looked at one layer at a time.
export function useResinLayers(jobId: string | null) {
	const [preview, setPreview] = useState<LayerPreviewStatus>(NONE);
	const [index, setIndex] = useState(0);
	// Whether the layer image is shown in place of the model.
	const [open, setOpen] = useState(false);
	const polls = useRef(0);

	// A new job starts again from no preview.
	// biome-ignore lint/correctness/useExhaustiveDependencies: restarts when the job changes
	useEffect(() => {
		setPreview(NONE);
		setIndex(0);
		setOpen(false);
		polls.current = 0;
	}, [jobId]);

	// Waits for the preview the server is making: asks until it is ready or failed (or, for a job that has none, a few times).
	const waiting = preview.status === 'running' || (preview.status === 'none' && polls.current < POLLS_BEFORE_GIVING_UP);
	useEffect(() => {
		if (!jobId || !waiting) return;
		const timer = setInterval(() => {
			polls.current += 1;
			getLayerPreview(jobId)
				.then(setPreview)
				.catch(() => {});
		}, POLL_INTERVAL_MS);
		return () => clearInterval(timer);
	}, [jobId, waiting]);

	// The first time it is ready, the layer picture takes the model's place, as in the result mockup.
	const ready = preview.status === 'ready';
	// biome-ignore lint/correctness/useExhaustiveDependencies: opens once when this job's preview becomes ready
	useEffect(() => {
		if (ready) setOpen(true);
	}, [ready, jobId]);

	const request = useCallback(() => {
		if (!jobId) return;
		setOpen(true);
		startLayerPreview(jobId)
			.then(setPreview)
			.catch((err: Error) => setPreview({ ...NONE, status: 'failed', error: err.message }));
	}, [jobId]);

	return { preview, index, setIndex, open, setOpen, request };
}

export type ResinLayers = ReturnType<typeof useResinLayers>;
