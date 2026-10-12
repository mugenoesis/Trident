import type { AppCtx } from '../hooks/useAppController';
import MainDialogs from './MainDialogs';
import MainHeader from './MainHeader';
import MainLineUpDialog from './MainLineUpDialog';
import MainSettingsPanel from './MainSettingsPanel';
import MainToasts from './MainToasts';
import MainViewerPanel from './MainViewerPanel';

// The main screen: the model preview on the left, the printer, material and settings on the right, and the windows over them.
export default function MainView({ c }: { c: AppCtx }) {
	return (
		<div className="app">
			<MainHeader c={c} />
			<main className="app-main">
				<MainViewerPanel c={c} />
				<MainSettingsPanel c={c} />
			</main>
			<MainLineUpDialog c={c} />
			<MainDialogs c={c} />
			<MainToasts c={c} />
		</div>
	);
}
