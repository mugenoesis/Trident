import { useCallback, useEffect, useState } from 'react';
import { getLayerPreview, startLayerPreview } from '../api';
import { POLL_INTERVAL_MS } from '../appHelpers';
import type { LayerPreviewStatus } from '../types';

const NONE: LayerPreviewStatus = { status: 'none', layer_count: null, error: null };

// The layer images of a resin job: asked for once, made by a second slice, then looked at one layer at a time.
export function useResinLayers(jobId: string | null) {
	const [preview, setPreview] = useState<LayerPreviewStatus>(NONE);
	const [index, setIndex] = useState(0);
	// Whether the layer image is shown in place of the model.
	const [open, setOpen] = useState(false);

	// A new job starts again from no preview.
	// biome-ignore lint/correctness/useExhaustiveDependencies: restarts when the job changes
	useEffect(() => {
		setPreview(NONE);
		setIndex(0);
		setOpen(false);
	}, [jobId]);

	const running = preview.status === 'running';
	useEffect(() => {
		if (!jobId || !running) return;
		const timer = setInterval(() => {
			getLayerPreview(jobId)
				.then(setPreview)
				.catch(() => {});
		}, POLL_INTERVAL_MS);
		return () => clearInterval(timer);
	}, [jobId, running]);

	const request = useCallback(() => {
		if (!jobId) return;
		setOpen(true);
		startLayerPreview(jobId)
			.then(setPreview)
			.catch((err: Error) => setPreview({ status: 'failed', layer_count: null, error: err.message }));
	}, [jobId]);

	return { preview, index, setIndex, open, setOpen, request };
}

export type ResinLayers = ReturnType<typeof useResinLayers>;
