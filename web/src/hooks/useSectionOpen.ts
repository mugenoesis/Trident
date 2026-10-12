import { useEffect } from 'react';
import type { AppState, MainAppProps } from './useAppState';

export function useSectionOpen(c: AppState & Pick<MainAppProps, never>) {
	const {
		setPrinterSettingsOpen,
		selectedPrinterId,
		setMaterialSectionOpen,
		selectedMaterialId,
		setSettingsSectionOpen,
		selectedSettingsProfileId,
	} = c;

	useEffect(() => setPrinterSettingsOpen(!selectedPrinterId), [selectedPrinterId, setPrinterSettingsOpen]);
	useEffect(() => setMaterialSectionOpen(!selectedMaterialId), [selectedMaterialId, setMaterialSectionOpen]);
	useEffect(() => setSettingsSectionOpen(!selectedSettingsProfileId), [selectedSettingsProfileId, setSettingsSectionOpen]);
}
