import { layerImageUrl } from '../api';
import type { ResinState } from '../hooks/useResin';

// The left panel in place of the model: one layer as the printer will expose it (white is cured resin).
export default function ResinLayerPane({ r }: { r: ResinState }) {
	const { job, layers } = r;
	if (!job) return null;
	return (
		<div className="resin-layer-view">
			<img src={layerImageUrl(job.id, layers.index)} alt={`Layer ${layers.index + 1} as the printer will expose it`} />
			<button type="button" className="link-button" onClick={() => layers.setOpen(false)}>
				Back to model
			</button>
		</div>
	);
}
