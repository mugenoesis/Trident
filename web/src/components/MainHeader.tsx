import type { AppCtx } from '../hooks/useAppController';
import SettingsMenu from './SettingsMenu';

export default function MainHeader({ c }: { c: AppCtx }) {
	const { authStatus, onSwitchToMulti, onSwitchToSingle, onCreateUser, onLogout, sampleModels, handleLoadSample, catalogError } = c;
	return (
		<>
			<header className="app-header">
				<h1>
					<img src="/icon-192.png" alt="" width={46} height={46} />
					TridentSlicer
				</h1>
				<SettingsMenu
					status={authStatus}
					onSwitchToMulti={onSwitchToMulti}
					onSwitchToSingle={onSwitchToSingle}
					onCreateUser={onCreateUser}
					onLogout={onLogout}
					sampleModels={sampleModels}
					onLoadSample={handleLoadSample}
				/>
			</header>
			{catalogError && <div className="banner-error">Failed to load printer/settings catalog: {catalogError}</div>}
		</>
	);
}
