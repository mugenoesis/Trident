import './App.css';
import LoginGate from './components/LoginGate';
import MainView from './components/MainView';
import SetupGate from './components/SetupGate';
import { useAppController } from './hooks/useAppController';
import type { MainAppProps } from './hooks/useAppState';
import { useAuth } from './useAuth';

export default function App() {
	const auth = useAuth();

	if (!auth.status) return null; // brief first-load flash while /auth/status resolves

	if (auth.status.mode === 'unset') {
		return (
			<SetupGate
				onChooseSingle={() => auth.setup({ mode: 'single' })}
				onChooseMulti={(username, password) => auth.setup({ mode: 'multi', username, password })}
			/>
		);
	}

	if (auth.status.mode === 'multi' && !auth.status.logged_in) {
		return <LoginGate onLogin={auth.login} />;
	}

	return (
		<MainApp
			authStatus={auth.status}
			onSwitchToMulti={auth.switchToMulti}
			onSwitchToSingle={auth.switchToSingle}
			onCreateUser={auth.createUser}
			onLogout={auth.logout}
			onUpdateLastSelection={auth.updateLastSelection}
		/>
	);
}
function MainApp(props: MainAppProps) {
	const c = useAppController(props);
	return <MainView c={c} />;
}
