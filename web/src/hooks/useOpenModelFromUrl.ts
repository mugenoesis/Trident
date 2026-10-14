import { useEffect } from 'react';

/** The model id in a page address's `?model=<id>`, and the address with that part taken out (so a reload does not open it again). */
function modelFromAddress(search: string): { modelId: string | null; rest: string } {
	const params = new URLSearchParams(search);
	const modelId = params.get('model');
	params.delete('model');
	const rest = params.toString();
	return { modelId: modelId || null, rest: rest ? `?${rest}` : '' };
}

// Someone sent a model here (Holecraft's "Send to Trident" uploads it with an API key, then opens this page at `?model=<id>`).
// It runs once the page is past the login gates, since the model is the signed-in user's own.
export function useOpenModelFromUrl(open: (modelId: string) => Promise<unknown>) {
	useEffect(() => {
		const { modelId, rest } = modelFromAddress(window.location.search);
		if (!modelId) return;
		window.history.replaceState(null, '', window.location.pathname + rest + window.location.hash);
		open(modelId).catch(() => {
			// the upload status already shows the error
		});
	}, [open]);
}
