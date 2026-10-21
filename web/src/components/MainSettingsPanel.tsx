import { deleteImportedProfile, listPrinters } from '../api';
import { COLOR_PRESETS, FALLBACK_NOZZLE_TYPES, MAX_FILAMENT_SLOTS, nozzleTypeLabel } from '../appHelpers';
import type { AppCtx } from '../hooks/useAppController';
import AdvancedSettings from './AdvancedSettings';
import CopiesControl from './CopiesControl';
import FilamentSelect from './FilamentSelect';
import JobPanel from './JobPanel';
import PrinterSelect from './PrinterSelect';
import QuickSettings, { QUICK_SETTING_KEYS } from './QuickSettings';
import ResinPanel from './ResinPanel';
import SavedPrinters from './SavedPrinters';
import SavedProfilePicker from './SavedProfilePicker';
import TechnologyToggle from './TechnologyToggle';

// The right-hand panel: a switch between filament and resin printers, then the settings of the one chosen.
export default function MainSettingsPanel({ c }: { c: AppCtx }) {
	const { resin } = c;
	return (
		<section className="panel panel-settings">
			<h2>Printer, material &amp; settings</h2>
			<TechnologyToggle technology={resin.technology} onChange={c.switchTechnology} />
			<SavedPrinters
				printers={c.printers}
				selectedPrinterId={c.selectedPrinterId}
				onSelectPrinter={c.applySavedPrinter}
				canSaveCurrent={canSaveCurrent(c)}
				onSavePrinter={c.handleSavePrinter}
				onUpdatePrinter={c.handleUpdatePrinter}
				onDeletePrinter={c.handleDeletePrinter}
				onPrintersAdded={() => {
					listPrinters()
						.then(c.setPrinters)
						.catch(() => undefined);
				}}
				technology={resin.technology}
			/>
			{resin.technology === 'resin' ? <ResinPanel r={resin} fileName={c.file?.name ?? ''} /> : <FdmSettings c={c} />}
		</section>
	);
}

// Whether the current setup can be saved as a printer: a resin printer is enough in resin mode, a filament one needs its profiles.
function canSaveCurrent(c: AppCtx): boolean {
	if (c.resin.technology === 'resin') return Boolean(c.resin.printerName);
	return Boolean(c.vendor && c.printerName && c.processName && c.filamentSlotsFilled);
}

function FdmSettings({ c }: { c: AppCtx }) {
	const {
		selectedPrinterId,
		vendor,
		printerName,
		processName,
		printerSettingsOpen,
		setPrinterSettingsOpen,
		selectedPrinter,
		profiles,
		handleVendorChange,
		handlePrinterChange,
		handleProcessChange,
		setImportOpen,
		setExportOpen,
		setPrinterDialog,
		refreshProfiles,
		materialSectionOpen,
		setMaterialSectionOpen,
		selectedMaterial,
		isMultiHeadPrinter,
		globalNozzleDiameter,
		setGlobalNozzleDiameter,
		globalNozzleType,
		setGlobalNozzleType,
		schema,
		filamentSlots,
		handleFilamentSlotChange,
		setMaterialDialog,
		handleDeleteCustomFilament,
		removeFilamentSlot,
		addFilamentSlot,
		materials,
		selectedMaterialId,
		applyMaterialProfile,
		handleDeselectMaterial,
		handleSaveMaterial,
		handleUpdateMaterial,
		handleRenameMaterial,
		handleDuplicateMaterial,
		handleDeleteMaterial,
		settingsSectionOpen,
		setSettingsSectionOpen,
		selectedSettingsProfile,
		quickSettings,
		handleQuickSettingsChange,
		bedSize,
		allowedBedTypes,
		settingsProfiles,
		selectedSettingsProfileId,
		applySettingsProfile,
		handleDeselectSettingsProfile,
		handleSaveSettingsProfile,
		handleUpdateSettingsProfile,
		handleRenameSettingsProfile,
		handleDuplicateSettingsProfile,
		handleDeleteSettingsProfile,
		advancedOverrides,
		handleAdvancedOverridesChange,
		modelId,
		copies,
		setCopies,
		setViewMode,
		isBeltPrinter,
		beltGapMm,
		setBeltGapMm,
		keptObjects,
		dimensions,
		canSlice,
		alreadySliced,
		handleSlice,
		slicing,
		currentJob,
		history,
		viewJobGcode,
		handleDeleteJob,
	} = c;
	return (
		<>
			<details className="settings-collapsible" open={printerSettingsOpen} onToggle={(e) => setPrinterSettingsOpen(e.currentTarget.open)}>
				<summary>Printer settings{selectedPrinter ? ` (${selectedPrinter.name})` : ''}</summary>
				<PrinterSelect
					profiles={profiles}
					vendor={vendor}
					printerName={printerName}
					processName={processName}
					onVendorChange={handleVendorChange}
					onPrinterChange={handlePrinterChange}
					onProcessChange={handleProcessChange}
					onImportClick={() => setImportOpen(true)}
					onExportClick={() => setExportOpen(true)}
					onNewPrinter={() => setPrinterDialog({ mode: 'create' })}
					onEditPrinter={() => setPrinterDialog({ mode: 'edit' })}
					onDeleteImportedPrinter={() => {
						if (!printerName) return;
						deleteImportedProfile('machine', printerName)
							.then(() => {
								handleVendorChange(vendor);
								refreshProfiles();
							})
							.catch((err: Error) => alert(`Failed to delete the imported printer: ${err.message}`));
					}}
				/>
			</details>

			<details className="settings-collapsible" open={materialSectionOpen} onToggle={(e) => setMaterialSectionOpen(e.currentTarget.open)}>
				<summary>Material{selectedMaterial ? ` (${selectedMaterial.name})` : ''}</summary>
				{!isMultiHeadPrinter && (
					<div className="field-group nozzle-diameter-global">
						<label>
							Nozzle diameter (mm)
							<input
								type="number"
								step="0.1"
								min="0"
								placeholder="e.g. 0.4"
								value={globalNozzleDiameter}
								onChange={(e) => setGlobalNozzleDiameter(e.target.value)}
							/>
						</label>
						<label>
							Nozzle type
							<select value={globalNozzleType} onChange={(e) => setGlobalNozzleType(e.target.value)}>
								{(schema.find((s) => s.key === 'nozzle_type')?.enum_values ?? FALLBACK_NOZZLE_TYPES).map((t) => (
									<option key={t} value={t}>
										{nozzleTypeLabel(t)}
									</option>
								))}
							</select>
						</label>
					</div>
				)}
				{filamentSlots.map((slot, i) => (
					// biome-ignore lint/suspicious/noArrayIndexKey: a fixed, position-ordered list that is never reordered
					<div className="filament-slot-row" key={i}>
						<FilamentSelect
							profiles={profiles}
							vendor={vendor}
							printerName={printerName}
							filamentName={slot.profile}
							onFilamentChange={(name) => handleFilamentSlotChange(i, { profile: name })}
							onNewMaterial={(base) => setMaterialDialog({ mode: 'create', slot: i, base: { vendor: base.vendor, name: base.name } })}
							onEditMaterial={(m) => setMaterialDialog({ mode: 'edit', slot: i, base: { vendor: m.vendor, name: m.name } })}
							onDeleteMaterial={(m) => void handleDeleteCustomFilament(i, m.name)}
							label={filamentSlots.length > 1 ? `Slot ${i + 1} material` : 'Material'}
							accessory={
								<input
									type="color"
									className="filament-slot-color-input"
									value={slot.color}
									onChange={(e) => handleFilamentSlotChange(i, { color: e.target.value })}
									aria-label={`Slot ${i + 1} color`}
								/>
							}
							belowLabel={
								<div className="color-preset-row">
									{COLOR_PRESETS.map(({ hex, name }) => (
										<button
											key={hex}
											type="button"
											className={`color-preset-swatch${slot.color === hex ? ' selected' : ''}`}
											style={{ background: hex }}
											aria-label={name}
											title={name}
											onClick={() => handleFilamentSlotChange(i, { color: hex })}
										/>
									))}
								</div>
							}
						/>
						{isMultiHeadPrinter && (
							<div className="field-group nozzle-diameter-per-slot">
								<label>
									{`Slot ${i + 1} nozzle diameter (mm)`}
									<input
										type="number"
										step="0.1"
										min="0"
										value={slot.nozzleDiameter}
										onChange={(e) => handleFilamentSlotChange(i, { nozzleDiameter: Number(e.target.value) })}
									/>
								</label>
								<label>
									{`Slot ${i + 1} nozzle type`}
									<select value={slot.nozzleType} onChange={(e) => handleFilamentSlotChange(i, { nozzleType: e.target.value })}>
										{(schema.find((s) => s.key === 'nozzle_type')?.enum_values ?? FALLBACK_NOZZLE_TYPES).map((t) => (
											<option key={t} value={t}>
												{nozzleTypeLabel(t)}
											</option>
										))}
									</select>
								</label>
							</div>
						)}
						{filamentSlots.length > 1 && (
							<button
								type="button"
								className="link-button danger-text filament-slot-remove"
								onClick={() => removeFilamentSlot(i)}
								aria-label={`Remove slot ${i + 1}`}
							>
								✕ Remove slot
							</button>
						)}
					</div>
				))}
				<button
					type="button"
					className="link-button filament-slot-add"
					onClick={addFilamentSlot}
					disabled={filamentSlots.length >= MAX_FILAMENT_SLOTS}
				>
					+ Add material slot
				</button>
				{selectedPrinterId && (
					<SavedProfilePicker
						label="material profile"
						profiles={materials}
						selectedId={selectedMaterialId}
						onSelect={applyMaterialProfile}
						onDeselect={handleDeselectMaterial}
						onSave={handleSaveMaterial}
						onUpdate={handleUpdateMaterial}
						onRename={handleRenameMaterial}
						onDuplicate={handleDuplicateMaterial}
						onDelete={handleDeleteMaterial}
					/>
				)}
			</details>

			<details className="settings-collapsible" open={settingsSectionOpen} onToggle={(e) => setSettingsSectionOpen(e.currentTarget.open)}>
				<summary>Settings{selectedSettingsProfile ? ` (${selectedSettingsProfile.name})` : ''}</summary>
				<QuickSettings
					schema={schema}
					values={quickSettings}
					onChange={handleQuickSettingsChange}
					isBelt={bedSize?.beltPrinterInfiniteY === true}
					allowedBedTypes={allowedBedTypes}
				/>
				{selectedPrinterId && (
					<SavedProfilePicker
						label="settings profile"
						profiles={settingsProfiles}
						selectedId={selectedSettingsProfileId}
						onSelect={applySettingsProfile}
						onDeselect={handleDeselectSettingsProfile}
						onSave={handleSaveSettingsProfile}
						onUpdate={handleUpdateSettingsProfile}
						onRename={handleRenameSettingsProfile}
						onDuplicate={handleDuplicateSettingsProfile}
						onDelete={handleDeleteSettingsProfile}
					/>
				)}
			</details>

			<AdvancedSettings
				schema={schema}
				overrides={advancedOverrides}
				onChange={handleAdvancedOverridesChange}
				excludeKeys={QUICK_SETTING_KEYS}
			/>

			{modelId && printerName && (
				<CopiesControl
					copies={copies}
					onCopiesChange={(n) => {
						setCopies(n);
						setViewMode('model');
					}}
					isBelt={isBeltPrinter}
					gapMm={beltGapMm}
					onGapChange={setBeltGapMm}
					copyLengthMm={
						keptObjects.length > 0
							? keptObjects.reduce((sum, o) => sum + o.depth_mm, 0) + beltGapMm * (keptObjects.length - 1)
							: (dimensions?.y ?? 0)
					}
				/>
			)}

			<JobPanel
				canSlice={canSlice}
				alreadySliced={alreadySliced}
				onSlice={handleSlice}
				slicing={slicing}
				currentJob={currentJob}
				history={history}
				onPreview={viewJobGcode}
				onDelete={handleDeleteJob}
			/>
		</>
	);
}
