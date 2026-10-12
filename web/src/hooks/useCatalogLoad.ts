import { useEffect } from 'react';
import { getSettingsSchema, listJobs, listPrinters, listProfiles, listSampleModels } from '../api';
import { defaultQuickSettings } from '../components/QuickSettings';
import type { AppState, MainAppProps } from './useAppState';

export function useCatalogLoad(c: AppState & Pick<MainAppProps, never>) {
	const {
		setProfiles,
		setSchema,
		appliedSettingsProfileRef,
		setQuickSettings,
		setCatalogError,
		setHistory,
		setPrinters,
		setPrintersLoaded,
		setSampleModels,
	} = c;

	// Initial catalog load.
	// biome-ignore lint/correctness/useExhaustiveDependencies: the state setters and refs come in through the hook's context object, so Biome cannot see they are stable; the refs are read when it runs, on purpose
	useEffect(() => {
		Promise.all([listProfiles(), getSettingsSchema()])
			.then(([profileList, settingsSchema]) => {
				setProfiles(profileList);
				setSchema(settingsSchema.settings);
				// Skip if a real saved settings profile's values already won the
				// race (see appliedSettingsProfileRef above) -- this would otherwise
				// unconditionally stomp them back to bare defaults.
				if (!appliedSettingsProfileRef.current) {
					setQuickSettings(defaultQuickSettings(settingsSchema.settings));
				}
			})
			.catch((err: Error) => setCatalogError(err.message));

		listJobs()
			.then(setHistory)
			.catch(() => {
				/* history is a nice-to-have; ignore failures */
			});

		listPrinters()
			.then((list) => {
				setPrinters(list);
				setPrintersLoaded(true);
			})
			.catch(() => setPrintersLoaded(true));

		listSampleModels()
			.then(setSampleModels)
			.catch(() => {
				/* the settings menu's sample-model list is a nice-to-have; ignore failures */
			});
	}, []);
}
