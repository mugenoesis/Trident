import { useEffect } from 'react';
import type { AppState, MainAppProps } from './useAppState';

export function useNozzleRefs(c: AppState & Pick<MainAppProps, never>) {
	const { nozzleDiametersRef, nozzleDiameters, nozzleTypesRef, nozzleTypes } = c;

	// biome-ignore lint/correctness/useExhaustiveDependencies: the state setters and refs come in through the hook's context object, so Biome cannot see they are stable; the refs are read when it runs, on purpose
	useEffect(() => {
		nozzleDiametersRef.current = nozzleDiameters;
	}, [nozzleDiameters]);
	// biome-ignore lint/correctness/useExhaustiveDependencies: the state setters and refs come in through the hook's context object, so Biome cannot see they are stable; the refs are read when it runs, on purpose
	useEffect(() => {
		nozzleTypesRef.current = nozzleTypes;
	}, [nozzleTypes]);
}
