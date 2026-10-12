import { filamentGramsOf } from '../appHelpers';
import { SCALE_UNSUPPORTED_MESSAGE } from '../dimensions';
import type { AppCtx } from '../hooks/useAppController';
import ScaleControls from './ScaleControls';
import Uploader from './Uploader';
import Viewer from './Viewer';

// The upload box, the preview, and the size with the scale controls.
export default function ModelPreview({ c }: { c: AppCtx }) {
	const {
		currentJob,
		handleFileSelected,
		file,
		uploadStatus,
		meshReport,
		viewerRef,
		handleDimensions,
		bedSize,
		renderColorTree,
		quickSettings,
		hasObjectChoice,
		excludedObjects,
		showPositionPanel,
		placement,
		shownObjects,
		copies,
		rowLayout,
		setObjectThumbs,
		dimensions,
		handleApplyScale,
		scaling,
		scalable,
	} = c;
	return (
		<>
			<Uploader
				onFileSelected={handleFileSelected}
				fileName={file?.name ?? null}
				uploadStatus={uploadStatus}
				meshNote={meshReport?.fixed.length ? 'auto-fixed' : meshReport?.warnings.length ? 'mesh not watertight' : null}
			/>
			<Viewer
				ref={viewerRef}
				file={file}
				onDimensions={handleDimensions}
				bedSize={bedSize}
				colorTree={renderColorTree}
				filamentUsedGrams={filamentGramsOf(currentJob)}
				supportEnabled={quickSettings.enable_support === '1'}
				excludedObjects={hasObjectChoice ? [...excludedObjects] : undefined}
				placement={showPositionPanel ? placement : null}
				shownObjects={shownObjects}
				rowShifts={copies === 1 ? (rowLayout?.shifts ?? null) : null}
				onObjectThumbnails={setObjectThumbs}
			/>
			{dimensions && (
				<>
					<div className="dimensions-readout">
						{dimensions.x.toFixed(1)} × {dimensions.y.toFixed(1)} × {dimensions.z.toFixed(1)} mm
					</div>
					<ScaleControls
						dimensions={dimensions}
						onApply={handleApplyScale}
						applying={scaling}
						unsupportedReason={scalable ? undefined : SCALE_UNSUPPORTED_MESSAGE}
					/>
				</>
			)}
		</>
	);
}
