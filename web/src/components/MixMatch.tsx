import { useState } from 'react';
import { suggestMixes } from '../api';
import { closenessLabel, recipeText } from '../mixedColours';
import type { MixedFilament, MixSuggestion } from '../types';

// "Start from the colour you want": the server tries every pair and triple of the loaded filaments and the closest few are offered.
export default function MixMatch({ colours, names, onPick }: { colours: string[]; names: string[]; onPick: (mix: MixedFilament) => void }) {
	const [target, setTarget] = useState('#4caf50');
	const [found, setFound] = useState<MixSuggestion[] | null>(null);
	const [problem, setProblem] = useState('');
	const find = () => {
		setProblem('');
		suggestMixes(colours, target, 4)
			.then(setFound)
			.catch((err: Error) => setProblem(`Could not look for mixes: ${err.message}`));
	};
	return (
		<div className="mix-match">
			<span className="mix-hint">Or start from the colour you want</span>
			<div className="mix-match-row">
				<input type="color" value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Wanted colour" />
				<button type="button" onClick={find}>
					Find mixes
				</button>
			</div>
			{problem && <span className="field-error">{problem}</span>}
			{found?.map((s) => (
				<button type="button" className="mix-suggestion" key={`${s.components}-${s.weights}`} onClick={() => onPick(s)}>
					<span className="mix-swatch" style={{ background: s.colour }} />
					<span className="mix-suggestion-text">
						{recipeText(s, names)}
						<small>{`${closenessLabel(s.distance)} (difference ${s.distance.toFixed(1)})`}</small>
					</span>
				</button>
			))}
		</div>
	);
}
