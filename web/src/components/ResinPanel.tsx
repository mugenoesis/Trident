import type { ReactNode } from 'react';
import { archiveDownloadUrl } from '../api';
import type { ResinState } from '../hooks/useResin';
import type { ResinLayers } from '../hooks/useResinLayers';
import {
	choiceNote,
	formatDuration,
	formatMl,
	MY_RESINS,
	PAD_MODES,
	type PadMode,
	RESIN_LAYER_HEIGHTS,
	RESIN_VALUE_FIELDS,
	resinDisplayName,
	SUPPORT_LEVELS,
	type SupportLevel,
	uniqueVendors,
} from '../resinSettings';
import type { JobRecord } from '../types';
import MyResinForm from './MyResinForm';

function PrinterSection({ r }: { r: ResinState }) {
	const { printers, printer, printerName, setPrinterName, catalogError } = r;
	const vendor = printer?.vendor ?? '';
	const models = printers.filter((p) => p.vendor === vendor);
	return (
		<details className="settings-collapsible" open>
			<summary>
				Printer settings{printer ? ` (${printer.name})` : ''} <span className="tech-badge resin">Resin</span>
			</summary>
			{catalogError && <div className="job-error">{catalogError}</div>}
			<Field label="Printer vendor" id="resin-printer-vendor">
				<select
					id="resin-printer-vendor"
					value={vendor}
					onChange={(e) => setPrinterName(printers.find((p) => p.vendor === e.target.value)?.name ?? '')}
				>
					<option value="">Select a vendor</option>
					{uniqueVendors(printers).map((v) => (
						<option key={v} value={v}>
							{v}
						</option>
					))}
				</select>
			</Field>
			<Field label="Printer" id="resin-printer">
				<select id="resin-printer" value={printerName} disabled={!vendor} onChange={(e) => setPrinterName(e.target.value)}>
					<option value="">Select a printer</option>
					{models.map((p) => (
						<option key={p.name} value={p.name}>
							{p.model}
							{p.supported ? '' : ` (.${p.extension} not supported yet)`}
						</option>
					))}
				</select>
			</Field>
			{printer && <PrinterFacts printer={printer} />}
		</details>
	);
}

function PrinterFacts({ printer }: { printer: NonNullable<ResinState['printer']> }) {
	const { pixels_x, pixels_y, display_width_mm, display_height_mm, pixel_size_mm, build_height_mm } = printer;
	return (
		<div className="resin-facts">
			{pixels_x && pixels_y && display_width_mm && display_height_mm && (
				<p>
					<strong>Screen</strong> {pixels_x} × {pixels_y} px over {display_width_mm} × {display_height_mm} mm
					{pixel_size_mm ? ` (${pixel_size_mm} mm per pixel)` : ''}
				</p>
			)}
			{build_height_mm && (
				<p>
					<strong>Build height</strong> {build_height_mm} mm
				</p>
			)}
			<p>
				<strong>Writes</strong> .{printer.extension} for the {printer.model}
				{printer.supported ? '' : ', which the slicer cannot write yet'}
			</p>
		</div>
	);
}

function ResinSection({ r }: { r: ResinState }) {
	const { resins, resinName, setResinName, printer, choice, choiceError, values, setValues } = r;
	const current = resins.find((x) => x.name === resinName);
	const vendor = current?.vendor ?? '';
	const names = resins.filter((x) => x.vendor === vendor);
	return (
		<details className="settings-collapsible" open>
			<summary>Resin{current ? ` (${current.name})` : ''}</summary>
			<Field label="Resin vendor" id="resin-resin-vendor">
				<select
					id="resin-resin-vendor"
					value={vendor}
					onChange={(e) => setResinName(resins.find((x) => x.vendor === e.target.value)?.name ?? '')}
				>
					<option value="">Select a vendor</option>
					{uniqueVendors(resins).map((v) => (
						<option key={v} value={v}>
							{v}
						</option>
					))}
				</select>
			</Field>
			<Field label="Resin" id="resin-resin">
				<select id="resin-resin" value={resinName} disabled={!vendor} onChange={(e) => setResinName(e.target.value)}>
					<option value="">Select a resin</option>
					{names.map((x) => (
						<option key={x.name} value={x.name}>
							{resinDisplayName(x)}
							{x.family ? ` (${x.family})` : ''}
						</option>
					))}
				</select>
			</Field>
			{choiceError && <div className="job-error">{choiceError}</div>}
			{choice && printer && (
				<div className={`resin-note${choice.match === 'exact' && choice.exact_layer_height ? ' good' : ''}`}>
					{choiceNote(choice, vendor, printer)}{' '}
					{choice.source.startsWith('http') && (
						<a href={choice.source} target="_blank" rel="noreferrer">
							Source
						</a>
					)}
				</div>
			)}
			{current && (
				<div className="resin-values">
					{RESIN_VALUE_FIELDS.map(({ key, label, unit }) => (
						<div key={key} className="field-group resin-value">
							<label htmlFor={`resin-${key}`}>{label}</label>
							<span className="resin-value-input">
								<input
									id={`resin-${key}`}
									type="number"
									min="0"
									step="any"
									value={values[key]}
									onChange={(e) => setValues({ ...values, [key]: e.target.value })}
								/>
								<span className="resin-unit">{unit}</span>
							</span>
						</div>
					))}
				</div>
			)}
			{current && (
				<MyResinForm
					chosenIsMine={current.vendor === MY_RESINS}
					canSave={Boolean(printer)}
					onSave={r.makeMyResin}
					onDelete={r.removeMyResin}
				/>
			)}
		</details>
	);
}

function SettingsSection({ r }: { r: ResinState }) {
	const { process, setProcess } = r;
	const summary = `${process.layerHeight} mm, ${process.supports === 'none' ? 'no supports' : `${process.supports} supports`}${
		process.hollow ? `, hollow ${process.wallThickness} mm` : ''
	}`;
	return (
		<details className="settings-collapsible" open>
			<summary>Settings ({summary})</summary>
			<div className="resin-values">
				<Field label="Layer height" id="resin-layer-height">
					<select
						id="resin-layer-height"
						value={process.layerHeight}
						onChange={(e) => setProcess({ ...process, layerHeight: e.target.value })}
					>
						{RESIN_LAYER_HEIGHTS.map((h) => (
							<option key={h} value={h}>
								{h} mm
							</option>
						))}
					</select>
				</Field>
				<Field label="Supports" id="resin-supports">
					<select
						id="resin-supports"
						value={process.supports}
						onChange={(e) =>
							setProcess({
								...process,
								supports: e.target.value as SupportLevel,
							})
						}
					>
						{SUPPORT_LEVELS.map((s) => (
							<option key={s.value} value={s.value}>
								{s.label}
							</option>
						))}
					</select>
				</Field>
				<Field label="Touchpoint size" id="resin-touchpoint-size">
					<input
						id="resin-touchpoint-size"
						type="number"
						min="0.1"
						step="0.05"
						value={process.touchpoint}
						disabled={process.supports === 'none'}
						onChange={(e) => setProcess({ ...process, touchpoint: e.target.value })}
					/>
				</Field>
				<Field label="Pad" id="resin-pad">
					<select id="resin-pad" value={process.pad} onChange={(e) => setProcess({ ...process, pad: e.target.value as PadMode })}>
						{PAD_MODES.map((p) => (
							<option key={p.value} value={p.value}>
								{p.label}
							</option>
						))}
					</select>
				</Field>
			</div>
			<label className="resin-check">
				<input type="checkbox" checked={process.hollow} onChange={(e) => setProcess({ ...process, hollow: e.target.checked })} />
				Hollow the model, wall thickness
				<input
					type="number"
					min="0.5"
					step="0.1"
					aria-label="Wall thickness"
					value={process.wallThickness}
					disabled={!process.hollow}
					onChange={(e) => setProcess({ ...process, wallThickness: e.target.value })}
				/>
				mm
			</label>
			<p className="job-hint">Exposure and lift come from the resin; change them above for this slice only.</p>
		</details>
	);
}

function Stat({ label, value }: { label: string; value: string }) {
	return (
		<div className="resin-stat">
			<span className="resin-stat-label">{label}</span>
			<strong>{value}</strong>
		</div>
	);
}

function number(job: JobRecord, key: string): number | null {
	const v = job.result?.[key];
	return typeof v === 'number' ? v : null;
}

function ResinResult({ job, archiveName, layers }: { job: JobRecord; archiveName: string; layers: ResinLayers }) {
	const layerCount = number(job, 'layer_count');
	const seconds = number(job, 'estimated_print_time_s');
	const ml = number(job, 'resin_used_ml');
	return (
		<div className="resin-result">
			<h3>
				<span>Sliced</span> <small>for {job.printer_profile}</small>
			</h3>
			<div className="resin-stats">
				{layerCount !== null && <Stat label="Layers" value={layerCount.toLocaleString()} />}
				{seconds !== null && <Stat label="Print time" value={formatDuration(seconds)} />}
				{ml !== null && <Stat label="Resin" value={formatMl(ml)} />}
			</div>
			<LayerControls job={job} layers={layers} />
			<a className="download-button" href={archiveDownloadUrl(job.id)} download>
				Download {archiveName}
			</a>
			<p className="job-hint">Copy the file to the printer's USB stick. Sending over Wi-Fi isn't available for this printer.</p>
		</div>
	);
}

export default function ResinPanel({ r, fileName }: { r: ResinState; fileName: string }) {
	const { job, sliceError, canSlice, slice } = r;
	const active = job?.status === 'queued' || job?.status === 'running';
	const extension = r.printer ? `.${r.printer.extension}` : '';
	const stem = fileName.replace(/\.[^.]+$/, '') || 'model';
	return (
		<>
			<PrinterSection r={r} />
			<ResinSection r={r} />
			<SettingsSection r={r} />
			<div className="job-panel">
				<button className="slice-button" type="button" disabled={!canSlice} onClick={slice}>
					{active ? 'Slicing…' : 'Slice'}
				</button>
				{active && job.progress?.message && <div className="job-progress-message">{job.progress.message}</div>}
				{sliceError && <div className="job-error">{sliceError}</div>}
				{job?.status === 'failed' && <div className="job-error">{job.error ?? 'Slicing failed'}</div>}
				{job?.status === 'succeeded' && <ResinResult job={job} archiveName={`${stem}${extension}`} layers={r.layers} />}
			</div>
		</>
	);
}

// A labelled input; the label sits beside the input, not around it, so that its name is just its text.
function Field({ label, id, children }: { label: string; id: string; children: ReactNode }) {
	return (
		<div className="field-group">
			<label htmlFor={id}>{label}</label>
			{children}
		</div>
	);
}

// Ask for the layer images, then a slider through them (the picture itself is in the left panel, see ResinLayerPane).
function LayerControls({ job, layers }: { job: JobRecord; layers: ResinLayers }) {
	const { preview, index, setIndex, open, setOpen, request } = layers;
	const height = number(job, 'layer_height_mm');
	if (preview.status === 'none' || preview.status === 'failed') {
		return (
			<div className="resin-layers">
				<button type="button" className="preview-button" onClick={request}>
					Preview layers
				</button>
				{preview.error && <div className="job-error">{preview.error}</div>}
			</div>
		);
	}
	if (preview.status === 'running') return <div className="job-hint">Preparing the layer preview…</div>;
	const count = preview.layer_count ?? 0;
	return (
		<div className="resin-layers">
			<div className="resin-layer-label">
				Layer {(index + 1).toLocaleString()} of {count.toLocaleString()}
				{height !== null && ` · ${((index + 1) * height).toFixed(2)} mm`}
			</div>
			<input
				type="range"
				aria-label="Layer"
				min={0}
				max={Math.max(0, count - 1)}
				value={index}
				onChange={(e) => {
					setIndex(Number(e.target.value));
					setOpen(true);
				}}
			/>
			{!open && (
				<button type="button" className="link-button" onClick={() => setOpen(true)}>
					Show layer
				</button>
			)}
		</div>
	);
}
