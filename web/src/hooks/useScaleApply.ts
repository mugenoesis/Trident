import { useCallback } from 'react';
import { type Dimensions, scaleStlFile } from '../dimensions';
import type { AppState, MainAppProps } from './useAppState';
import type { useModelUpload } from './useModelUpload';
import type { useScaleFit } from './useScaleFit';

export function useScaleApply(
	c: AppState & Pick<MainAppProps, never> & ReturnType<typeof useModelUpload> & ReturnType<typeof useScaleFit>,
) {
	const { file, setScaling, handleFileSelected, fitScale } = c;

	// Shared by the auto-fit toast (uniform factor on all three axes) and the
	// manual ScaleControls panel (which can send different factors per axis).
	const handleApplyScale = useCallback(
		(factors: Dimensions) => {
			if (!file) return;
			setScaling(true);
			scaleStlFile(file, factors)
				.then((scaled) => handleFileSelected(scaled))
				.catch((err: Error) => alert(`Failed to scale model: ${err.message}`))
				.finally(() => setScaling(false));
		},
		[file, handleFileSelected, setScaling],
	);

	const handleAcceptScaleToFit = useCallback(() => {
		if (fitScale === null) return;
		handleApplyScale({ x: fitScale, y: fitScale, z: fitScale });
	}, [fitScale, handleApplyScale]);
	return { handleApplyScale, handleAcceptScaleToFit };
}
