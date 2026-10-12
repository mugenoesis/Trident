import { useEffect } from 'react';
import type { AppState, MainAppProps } from './useAppState';
import type { useObjectsView } from './useObjectsView';
import type { useSlice } from './useSlice';

export function useLineUp(c: AppState & Pick<MainAppProps, never> & ReturnType<typeof useObjectsView> & ReturnType<typeof useSlice>) {
	const {
		currentJob,
		isBeltPrinter,
		hasObjectChoice,
		beltRowActive,
		lineUpAnsweredFor,
		retryAfterLineUp,
		setRetryAfterLineUp,
		handleSlice,
	} = c;

	// On a belt printer a multi-object file with "line up" off goes through the
	// slicer's own arrange, which can fail to fit the objects on the bed. Offer
	// the row layout instead, and slice again if the user agrees.
	const needsLineUpQuestion =
		currentJob?.status === 'failed' &&
		Boolean(currentJob.error?.includes('over the boundary of the heated bed')) &&
		isBeltPrinter &&
		hasObjectChoice &&
		!beltRowActive &&
		lineUpAnsweredFor !== currentJob.id;
	useEffect(() => {
		if (retryAfterLineUp && beltRowActive) {
			setRetryAfterLineUp(false);
			handleSlice();
		}
	}, [retryAfterLineUp, beltRowActive, handleSlice, setRetryAfterLineUp]);
	return { needsLineUpQuestion };
}
