import type { AppCtx } from '../hooks/useAppController';
import GcodePane from './GcodePane';
import ModelPreview from './ModelPreview';
import NozzleAssignment from './NozzleAssignment';
import ObjectsSection from './ObjectsSection';
import PositionSection from './PositionSection';

// The left panel: the model with its controls, or the sliced G-code once a job is being looked at.
export default function MainViewerPanel({ c }: { c: AppCtx }) {
	const jobId = c.showGcode ? c.viewedJobId : null;
	return (
		<section className="panel panel-viewer">
			{jobId ? (
				<GcodePane c={c} jobId={jobId} />
			) : (
				<>
					<ModelPreview c={c} />
					<PositionSection c={c} />
					<ObjectsSection c={c} />
					<NozzleAssignment c={c} />
				</>
			)}
		</section>
	);
}
