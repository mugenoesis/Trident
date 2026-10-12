import { IMPORTED_VENDOR } from '../appHelpers';
import type { AppCtx } from '../hooks/useAppController';
import ExportDialog from './ExportDialog';
import MaterialDialog from './MaterialDialog';
import PrinterDialog from './PrinterDialog';
import ProfileImportDialog from './ProfileImportDialog';
import RotateMoveDialog from './RotateMoveDialog';

export default function MainDialogs({ c }: { c: AppCtx }) {
	const {
		importOpen,
		setImportOpen,
		refreshProfiles,
		exportOpen,
		setExportOpen,
		printerDialog,
		printerName,
		vendor,
		profiles,
		schema,
		setPrinterDialog,
		handlePrinterSaved,
		rotateMoveOpen,
		file,
		bedSize,
		showRotateMove,
		quickSettings,
		multiPlate,
		placement,
		objects,
		objectThumbs,
		plateIndex,
		positionBusy,
		setRotateMoveOpen,
		setPlacement,
		setViewMode,
		handleTransformModel,
		handleTransformObjects,
		runModelOp,
		materialDialog,
		setMaterialDialog,
		handleMaterialSaved,
	} = c;
	return (
		<>
			{importOpen && <ProfileImportDialog onClose={() => setImportOpen(false)} onChanged={refreshProfiles} />}
			{exportOpen && <ExportDialog onClose={() => setExportOpen(false)} />}
			{printerDialog && (
				<PrinterDialog
					mode={printerDialog.mode}
					current={
						printerDialog.mode === 'edit' || printerName
							? { vendor: printerDialog.mode === 'edit' ? IMPORTED_VENDOR : vendor, name: printerName }
							: null
					}
					profiles={profiles}
					schema={schema}
					onClose={() => setPrinterDialog(null)}
					onSaved={handlePrinterSaved}
				/>
			)}
			{rotateMoveOpen && file && bedSize && showRotateMove && (
				<RotateMoveDialog
					file={file}
					bedSize={bedSize}
					supportEnabled={quickSettings.enable_support === '1'}
					placement={multiPlate ? null : placement}
					objectNames={objects.map((o) => o.name)}
					thumbnails={objectThumbs}
					plateObjects={multiPlate ? objects.filter((o) => o.plate === plateIndex).map((o) => o.index) : undefined}
					busyOp={positionBusy}
					onClose={() => setRotateMoveOpen(false)}
					onPlace={(p) => {
						setPlacement(p);
						setViewMode('model');
					}}
					onTransform={handleTransformModel}
					onTransformObjects={handleTransformObjects}
					onAutoOrient={() => runModelOp('orient')}
					onAutoArrange={() => runModelOp('arrange')}
				/>
			)}
			{materialDialog && (
				<MaterialDialog
					mode={materialDialog.mode}
					base={materialDialog.base}
					printerName={printerName}
					schema={schema}
					onClose={() => setMaterialDialog(null)}
					onSaved={(name) => handleMaterialSaved(materialDialog.slot, name)}
				/>
			)}
		</>
	);
}
