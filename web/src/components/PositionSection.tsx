import type { AppCtx } from '../hooks/useAppController';
import PositionPanel from './PositionPanel';

// The Rotate and move button and where the model sits.
export default function PositionSection({ c }: { c: AppCtx }) {
	const {
		bedSize,
		quickSettings,
		placement,
		dimensions,
		showRotateMove,
		multiPlate,
		plateIndex,
		objects,
		setPlacement,
		setViewMode,
		setRotateMoveOpen,
	} = c;
	return (
		<>
			{showRotateMove && bedSize && dimensions && (
				<PositionPanel
					bedSize={bedSize}
					plateSummary={
						multiPlate
							? `Plate ${plateIndex}: ${objects.filter((o) => o.plate === plateIndex).length} object${objects.filter((o) => o.plate === plateIndex).length === 1 ? '' : 's'}`
							: undefined
					}
					supportEnabled={quickSettings.enable_support === '1'}
					placement={placement}
					onPlacementChange={(p) => {
						setPlacement(p);
						setViewMode('model');
					}}
					onOpen={() => setRotateMoveOpen(true)}
				/>
			)}
		</>
	);
}
