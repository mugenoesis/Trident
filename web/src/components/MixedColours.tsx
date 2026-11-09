import { useState } from 'react';
import { colorLabel } from '../appHelpers';
import type { AppCtx } from '../hooks/useAppController';
import { mixSlotIndex, recipeText } from '../mixedColours';
import MixEditor from './MixEditor';
import MixLayerStrip from './MixLayerStrip';

// "new" is the editor for a mix that does not exist yet, a number is the mix being changed.
type Editing = number | 'new' | null;

function SublayerChoice({ c }: { c: AppCtx }) {
	return (
		<>
			<label className="checkbox-label">
				<input type="checkbox" checked={c.mixSublayers} onChange={(e) => c.setMixSublayers(e.target.checked)} />
				Blend inside every layer
			</label>
			<span className="mix-hint">
				{c.mixSublayers
					? 'Every layer is split into thin passes, one per filament: a smoother blend, more tool changes, a slower print.'
					: 'Whole layers alternate by the ratio: faster, with the colours showing as fine stripes.'}
			</span>
		</>
	);
}

// The mixed colours of the printer, each as one more slot that a part of the model can be given.
export default function MixedColours({ c }: { c: AppCtx }) {
	const { filamentSlots, mixes, mixColours, addMix, updateMix, removeMix } = c;
	const [editing, setEditing] = useState<Editing>(null);
	const names = filamentSlots.map((s) => colorLabel(s.color));
	const colours = filamentSlots.map((s) => s.color);
	const save = (mix: (typeof mixes)[number]) => {
		if (editing === 'new') addMix(mix);
		else if (editing !== null) updateMix(editing, mix);
		setEditing(null);
	};
	return (
		<details className="settings-collapsible">
			<summary>{`Mixed colours${mixes.length > 0 ? ` (${mixes.length})` : ''}`}</summary>
			<p className="mix-hint">
				Print a colour your loaded filaments can't make alone: two or three of them alternate in thin layers and read as one colour. A mix
				then shows up as an extra slot you can give to a part of the model. Changing the number of filament slots clears your mixes.
			</p>
			{filamentSlots.length < 2 && <span className="mix-hint">Add a second material slot to mix colours.</span>}
			{mixes.map((mix, i) => (
				// biome-ignore lint/suspicious/noArrayIndexKey: mixes are identified by their position, which is their slot number
				<div className="mix-card" key={i}>
					<span className="mix-swatch big" style={{ background: mixColours[i] ?? 'transparent' }} />
					<MixLayerStrip mix={mix} colours={colours} />
					<span className="mix-card-info">
						<span className="mix-card-title">{`Slot ${mixSlotIndex(i, filamentSlots.length) + 1} · mix`}</span>
						<span className="mix-hint">{recipeText(mix, names)}</span>
						<span className="mix-card-actions">
							<button type="button" className="link-button" onClick={() => setEditing(i)}>
								Edit
							</button>
							<button type="button" className="link-button danger-text" onClick={() => removeMix(i)} aria-label={`Remove mix ${i + 1}`}>
								✕ Remove
							</button>
						</span>
					</span>
				</div>
			))}
			{editing !== null ? (
				<MixEditor
					// a fresh editor for each mix, so its picks do not carry over from the last one
					key={editing}
					initial={editing === 'new' ? null : mixes[editing]}
					names={names}
					colours={colours}
					onSave={save}
					onCancel={() => setEditing(null)}
				/>
			) : (
				<button type="button" className="link-button" onClick={() => setEditing('new')} disabled={filamentSlots.length < 2}>
					+ Add a mixed colour
				</button>
			)}
			{mixes.length > 0 && <SublayerChoice c={c} />}
		</details>
	);
}
