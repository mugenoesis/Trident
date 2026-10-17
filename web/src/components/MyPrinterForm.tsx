import { useState } from 'react';
import { checkPrinterNumbers, MY_PRINTERS, uniqueVendors } from '../resinSettings';
import type { MyResinPrinterRequest, ResinFormat, ResinPrinterInfo } from '../types';

interface MyPrinterFormProps {
	initial: MyResinPrinterRequest;
	// The name of the printer being changed; null for a new one (whose name is asked for).
	editing: string | null;
	printers: ResinPrinterInfo[];
	formats: ResinFormat[];
	onSave: (body: MyResinPrinterRequest, editing: string | null) => Promise<unknown>;
	onClose: () => void;
}

// A number the user types: kept as typed (so "218." can be on its way to "218.88") and given on as a number.
function NumberField({
	label,
	unit,
	value,
	step,
	onChange,
}: {
	label: string;
	unit?: string;
	value: number;
	step: string;
	onChange: (n: number) => void;
}) {
	const [text, setText] = useState(value ? String(value) : '');
	const id = `my-printer-${label.toLowerCase().replace(/ /g, '-')}`;
	return (
		<div className="field-group resin-value">
			<label htmlFor={id}>{label}</label>
			<span className="resin-value-input">
				<input
					id={id}
					type="number"
					min="0"
					step={step}
					value={text}
					onChange={(e) => {
						setText(e.target.value);
						onChange(Number(e.target.value));
					}}
				/>
				{unit && <span className="resin-unit">{unit}</span>}
			</span>
		</div>
	);
}

function BasedOn({
	value,
	printers,
	onChange,
}: {
	value: string | null;
	printers: ResinPrinterInfo[];
	onChange: (v: string | null) => void;
}) {
	const catalogue = printers.filter((p) => p.vendor !== MY_PRINTERS);
	return (
		<div className="field-group">
			<label htmlFor="my-printer-based-on">Based on</label>
			<select id="my-printer-based-on" value={value ?? ''} onChange={(e) => onChange(e.target.value || null)}>
				<option value="">None: start from scratch</option>
				{uniqueVendors(catalogue).map((v) => (
					<optgroup key={v} label={v}>
						{catalogue
							.filter((p) => p.vendor === v)
							.map((p) => (
								<option key={p.name} value={p.name}>
									{p.name}
								</option>
							))}
					</optgroup>
				))}
			</select>
			<span className="job-hint resin-hint">
				{value
					? 'Its resin settings, mirroring and delays are used. Resins publish their settings per printer model.'
					: 'Most resins publish settings only for the printers they name, so without a printer to be based on only resins of your own, and those for any printer, can be used.'}
			</span>
		</div>
	);
}

function Checkbox({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
	return (
		<label className="resin-check">
			<input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
			{label}
		</label>
	);
}

// The form for a resin printer of your own: its screen, build height and file format.
export default function MyPrinterForm({ initial, editing, printers, formats, onSave, onClose }: MyPrinterFormProps) {
	const [form, setForm] = useState(initial);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const set = (changes: Partial<MyResinPrinterRequest>) => setForm((prev) => ({ ...prev, ...changes }));
	const { problem, pitch } = checkPrinterNumbers(form);
	const extension = formats.find((f) => f.id === form.format)?.extension;
	const canSave = Boolean(form.name.trim() && pitch && !problem && form.build_height_mm > 0 && form.format);

	const submit = (e: React.FormEvent) => {
		e.preventDefault();
		setBusy(true);
		setError(null);
		onSave({ ...form, name: form.name.trim() }, editing)
			.then(onClose)
			.catch((err: Error) => setError(err.message))
			.finally(() => setBusy(false));
	};

	return (
		<form className="auth-form my-printer-form" onSubmit={submit}>
			<strong>Your printer</strong>
			<div className="field-group">
				<label htmlFor="my-printer-name">Name</label>
				<input id="my-printer-name" value={form.name} disabled={editing !== null} onChange={(e) => set({ name: e.target.value })} />
			</div>
			<BasedOn value={form.copy_from} printers={printers} onChange={(copy_from) => set({ copy_from })} />
			<div className="resin-values">
				<NumberField
					label="Screen width"
					unit="mm"
					step="any"
					value={form.display_width_mm}
					onChange={(n) => set({ display_width_mm: n })}
				/>
				<NumberField
					label="Screen height"
					unit="mm"
					step="any"
					value={form.display_height_mm}
					onChange={(n) => set({ display_height_mm: n })}
				/>
				<NumberField label="Pixels across" step="1" value={form.pixels_x} onChange={(n) => set({ pixels_x: n })} />
				<NumberField label="Pixels down" step="1" value={form.pixels_y} onChange={(n) => set({ pixels_y: n })} />
				<NumberField label="Build height" unit="mm" step="any" value={form.build_height_mm} onChange={(n) => set({ build_height_mm: n })} />
			</div>
			<div className="field-group">
				<label htmlFor="my-printer-format">File format</label>
				<select id="my-printer-format" value={form.format} onChange={(e) => set({ format: e.target.value })}>
					{formats.map((f) => (
						<option key={f.id} value={f.id}>
							{f.label}
						</option>
					))}
				</select>
				<span className="job-hint resin-hint">
					{extension ? `Writes .${extension}. ` : ''}Use the format your printer's own slicer exports.
				</span>
			</div>
			<Checkbox label="Mirror the image left to right" checked={form.mirror_x ?? false} onChange={(mirror_x) => set({ mirror_x })} />
			<Checkbox label="Mirror the image top to bottom" checked={form.mirror_y ?? false} onChange={(mirror_y) => set({ mirror_y })} />
			<Checkbox
				label="The pixels are rectangular (very few screens)"
				checked={form.rectangular_pixels}
				onChange={(rectangular_pixels) => set({ rectangular_pixels })}
			/>
			{problem && <div className="resin-warning">{problem}</div>}
			{!problem && pitch && (
				<div className="resin-note good">
					Pixel size {pitch.x.toFixed(4)} × {pitch.y.toFixed(4)} mm.
				</div>
			)}
			{error && <div className="job-error">{error}</div>}
			<div className="auth-form-actions">
				<button type="submit" disabled={busy || !canSave}>
					{busy ? 'Saving…' : 'Save printer'}
				</button>
				<button type="button" className="link-button" disabled={busy} onClick={onClose}>
					Cancel
				</button>
			</div>
		</form>
	);
}
