import { type MainAppProps, useAppState } from './useAppState';
import { useBedTypes } from './useBedTypes';
import { useBeltRow } from './useBeltRow';
import { useBrim } from './useBrim';
import { useCatalogLoad } from './useCatalogLoad';
import { useColorTree } from './useColorTree';
import { useJobActions } from './useJobActions';
import { useLineUp } from './useLineUp';
import { useMaterialCrud } from './useMaterialCrud';
import { useModelOps } from './useModelOps';
import { useModelUpload } from './useModelUpload';
import { useNozzleRefs } from './useNozzleRefs';
import { useObjectsView } from './useObjectsView';
import { useOpenModelFromUrl } from './useOpenModelFromUrl';
import { usePlateShown } from './usePlateShown';
import { usePolling } from './usePolling';
import { usePrimeTower } from './usePrimeTower';
import { usePrinterChoice } from './usePrinterChoice';
import { usePrinterCrud } from './usePrinterCrud';
import { usePrinterPending } from './usePrinterPending';
import { useProfileApply } from './useProfileApply';
import { useProfileHandlers } from './useProfileHandlers';
import { useProfileLists } from './useProfileLists';
import { useResetOnNewFile } from './useResetOnNewFile';
import { useResin } from './useResin';
import { useRestore } from './useRestore';
import { useRoles } from './useRoles';
import { useSavedPrinterApply } from './useSavedPrinterApply';
import { useScaleApply } from './useScaleApply';
import { useScaleFit } from './useScaleFit';
import { useSectionOpen } from './useSectionOpen';
import { useSelection } from './useSelection';
import { useSettingsCrud } from './useSettingsCrud';
import { useSignature } from './useSignature';
import { useSlice } from './useSlice';
import { useSlotHandlers } from './useSlotHandlers';
import { useVendorChange } from './useVendorChange';
import { useViewedJob } from './useViewedJob';

// Calls the hooks that work on the main screen's state, in the order their effects have to run, and hands back everything they made.
export function useAppController(props: MainAppProps) {
	const state = useAppState(props);
	const resin = useResin(state.modelId);
	useResetOnNewFile({ ...props, ...state });
	const primeTower = usePrimeTower({ ...props, ...state });
	const viewedJob = useViewedJob({ ...props, ...state });
	const selection = useSelection({ ...props, ...state });
	useSectionOpen({ ...props, ...state });
	const jobActions = useJobActions({ ...props, ...state });
	useCatalogLoad({ ...props, ...state });
	useNozzleRefs({ ...props, ...state });
	const profileApply = useProfileApply({ ...props, ...state });
	useProfileLists({ ...props, ...state, ...profileApply });
	const modelUpload = useModelUpload({ ...props, ...state });
	useOpenModelFromUrl(modelUpload.handleOpenModel);
	const modelOps = useModelOps({ ...props, ...state, ...modelUpload });
	const objectsView = useObjectsView({ ...props, ...state });
	const beltRow = useBeltRow({ ...props, ...state, ...objectsView });
	const scaleFit = useScaleFit({ ...props, ...state, ...objectsView, ...beltRow });
	const scaleApply = useScaleApply({ ...props, ...state, ...modelUpload, ...scaleFit });
	const printerChoice = usePrinterChoice({ ...props, ...state });
	const printerPending = usePrinterPending({ ...props, ...state, ...printerChoice });
	const vendorChange = useVendorChange({ ...props, ...state });
	useBrim({ ...props, ...state });
	const bedTypes = useBedTypes({ ...props, ...state });
	const profileHandlers = useProfileHandlers({ ...props, ...state });
	const slotHandlers = useSlotHandlers({ ...props, ...state, ...profileHandlers });
	const savedPrinterApply = useSavedPrinterApply({ ...props, ...state });
	const printerCrud = usePrinterCrud({ ...props, ...state });
	useRestore({ ...props, ...state, ...savedPrinterApply });
	const materialCrud = useMaterialCrud({ ...props, ...state });
	const settingsCrud = useSettingsCrud({ ...props, ...state });
	usePolling({ ...props, ...state, ...viewedJob });
	const roles = useRoles({ ...props, ...state });
	const colorTree = useColorTree({ ...props, ...state });
	const plateShown = usePlateShown({ ...props, ...state, ...objectsView });
	const signature = useSignature({ ...props, ...state, ...selection, ...roles, ...objectsView, ...plateShown });
	const slice = useSlice({ ...props, ...state, ...roles, ...signature, ...selection, ...objectsView });
	const lineUp = useLineUp({ ...props, ...state, ...objectsView, ...slice });
	return {
		...props,
		...state,
		resin,
		...primeTower,
		...viewedJob,
		...selection,
		...jobActions,
		...profileApply,
		...modelUpload,
		...modelOps,
		...objectsView,
		...beltRow,
		...scaleFit,
		...scaleApply,
		...printerChoice,
		...printerPending,
		...vendorChange,
		...bedTypes,
		...profileHandlers,
		...slotHandlers,
		...savedPrinterApply,
		...printerCrud,
		...materialCrud,
		...settingsCrud,
		...roles,
		...colorTree,
		...plateShown,
		...signature,
		...slice,
		...lineUp,
	};
}

export type AppCtx = ReturnType<typeof useAppController>;
