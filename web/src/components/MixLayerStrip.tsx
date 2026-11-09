import { layerColours } from '../mixedColours';
import type { MixedFilament } from '../types';

// The layers a mix prints, top to bottom of the picture as they stack up: a small picture of the alternation, not of the final colour.
export default function MixLayerStrip({ mix, colours }: { mix: MixedFilament; colours: string[] }) {
	const layers = layerColours(mix, colours).reverse();
	return (
		<span className="mix-strip" title="How the layers alternate">
			{layers.map((colour, i) => (
				// biome-ignore lint/suspicious/noArrayIndexKey: a fixed picture of layers that is never reordered
				<i key={i} style={{ background: colour }} />
			))}
		</span>
	);
}
