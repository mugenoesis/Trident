import { useState } from 'react';
import { useMixColours } from '../hooks/useMixedColours';
import { isComplete, MAX_MIX_COMPONENTS, setWeight, toggleComponent } from '../mixedColours';
import type { MixedFilament } from '../types';
import MixLayerStrip from './MixLayerStrip';
import MixMatch from './MixMatch';

interface EditorProps {
	initial: MixedFilament | null;
	names: string[];
	colours: string[];
	onSave: (mix: MixedFilament) => void;
	onCancel: () => void;
}

// Which 2 or 3 of the loaded filaments the mix is made of.
function FilamentPicker({
	mix,
	names,
	colours,
	onToggle,
}: {
	mix: MixedFilament;
	names: string[];
	colours: string[];
	onToggle: (slot: number) => void;
}) {
	const full = mix.components.length >= MAX_MIX_COMPONENTS;
	return (
		<div className="mix-pick-row">
			{names.map((name, i) => {
				const on = mix.components.includes(i + 1);
				return (
					<button
						// biome-ignore lint/suspicious/noArrayIndexKey: slots are a fixed, position-ordered list
						key={i}
						type="button"
						className={`mix-pick${on ? ' on' : ''}`}
						aria-pressed={on}
						disabled={!on && full}
						onClick={() => onToggle(i + 1)}
					>
						<span className="mix-swatch" style={{ background: colours[i] }} />
						{`Slot ${i + 1} · ${name}`}
					</button>
				);
			})}
		</div>
	);
}

// One slider per picked filament, showing its share of the total.
function WeightRows({ mix, names, onWeight }: { mix: MixedFilament; names: string[]; onWeight: (index: number, weight: number) => void }) {
	const total = mix.weights.reduce((a, b) => a + b, 0);
	return mix.components.map((slot, i) => (
		<label className="mix-weight-row" key={slot}>
			<span>{names[slot - 1]}</span>
			<input
				type="range"
				min={5}
				max={95}
				step={5}
				value={mix.weights[i]}
				onChange={(e) => onWeight(i, Number(e.target.value))}
				aria-label={`${names[slot - 1]} share`}
			/>
			<span className="mix-pct">{`${Math.round((mix.weights[i] / total) * 100)}%`}</span>
		</label>
	));
}

// The colour the mix is expected to give: an estimate from the server, with a picture of how the layers alternate.
function MixResult({ mix, colours }: { mix: MixedFilament; colours: string[] }) {
	const estimated = useMixColours(colours, isComplete(mix) ? [mix] : [])[0];
	if (!isComplete(mix)) return <span className="mix-hint">Pick at least two filaments to see the colour.</span>;
	return (
		<div className="mix-result">
			<span className="mix-swatch big" style={{ background: estimated ?? 'transparent' }} />
			<MixLayerStrip mix={mix} colours={colours} />
			<span className="mix-result-text">
				<b>{estimated ?? '…'}</b>
				<small>Estimated colour. Real prints vary with the filaments and the layer height.</small>
			</span>
		</div>
	);
}

export default function MixEditor({ initial, names, colours, onSave, onCancel }: EditorProps) {
	const [draft, setDraft] = useState<MixedFilament>(initial ?? { components: [], weights: [] });
	return (
		<div className="mix-editor">
			<h3>{initial ? 'Edit mix' : 'New mix'}</h3>
			<span className="mix-hint">Made of (pick 2 or 3 of your loaded filaments)</span>
			<FilamentPicker mix={draft} names={names} colours={colours} onToggle={(slot) => setDraft((d) => toggleComponent(d, slot))} />
			<WeightRows mix={draft} names={names} onWeight={(i, w) => setDraft((d) => setWeight(d, i, w))} />
			<MixResult mix={draft} colours={colours} />
			<MixMatch colours={colours} names={names} onPick={setDraft} />
			<div className="mix-editor-actions">
				<button type="button" disabled={!isComplete(draft)} onClick={() => onSave(draft)}>
					{initial ? 'Save mix' : 'Add mix'}
				</button>
				<button type="button" className="link-button" onClick={onCancel}>
					Cancel
				</button>
			</div>
		</div>
	);
}
