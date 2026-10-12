import type { AppCtx } from '../hooks/useAppController';
import ObjectPicker from './ObjectPicker';
import PlatePicker from './PlatePicker';

// Which objects of a multi-object file to print, and which plate.
export default function ObjectsSection({ c }: { c: AppCtx }) {
	const {
		hasObjectChoice,
		excludedObjects,
		plateIndex,
		objects,
		setObjectPickerOpen,
		keptObjects,
		objectSelectionOk,
		objectPickerOpen,
		objectThumbs,
		setExcludedObjects,
		isBeltPrinter,
		beltLineUp,
		setBeltLineUp,
		beltOrder,
		setBeltOrder,
		beltRowMode,
		setBeltRowMode,
		plateInfo,
		beltGapMm,
		setBeltGapMm,
		showPlatePicker,
		setPlateIndex,
	} = c;
	return (
		<>
			{hasObjectChoice && (
				<div className="field-group objects-button-row">
					<button type="button" className="link-button" onClick={() => setObjectPickerOpen(true)}>
						Objects ({keptObjects.length} of {objects.length} selected)
					</button>
					{keptObjects.length === 0 && <span className="field-error">Nothing selected to print</span>}
					{keptObjects.length > 0 && !objectSelectionOk && (
						<span className="field-error">Every object on the chosen plate is left out</span>
					)}
				</div>
			)}
			{objectPickerOpen && hasObjectChoice && (
				<ObjectPicker
					objects={objects}
					thumbnails={objectThumbs}
					excluded={excludedObjects}
					onExcludedChange={setExcludedObjects}
					isBelt={isBeltPrinter}
					lineUp={beltLineUp}
					onLineUpChange={setBeltLineUp}
					order={beltOrder}
					onOrderChange={setBeltOrder}
					rowMode={beltRowMode}
					onRowModeChange={setBeltRowMode}
					plateNames={Object.fromEntries((plateInfo?.plates ?? []).map((p) => [p.index, p.name ?? `Plate ${p.index}`]))}
					gapMm={beltGapMm}
					onGapChange={setBeltGapMm}
					onClose={() => setObjectPickerOpen(false)}
				/>
			)}
			{showPlatePicker && plateInfo && <PlatePicker plates={plateInfo.plates} plateIndex={plateIndex} onChange={setPlateIndex} />}
		</>
	);
}
