import { useCallback } from 'react';
import { downloadModelFile, getModelPlates, loadSampleModel, uploadModel } from '../api';
import type { Dimensions } from '../dimensions';
import type { ThreeMfInspection } from '../types';
import type { AppState, MainAppProps } from './useAppState';

export function useModelUpload(c: AppState & Pick<MainAppProps, never>) {
	const {
		setPlateInfo,
		setPlateIndex,
		setFile,
		setModelId,
		setUploadStatus,
		setScaleToastDismissed,
		setViewMode,
		setObjectThumbs,
		setObjectPickerOpen,
		setPlacement,
		setCopies,
		setMeshReport,
		setMeshToastDismissed,
		setDimensions,
	} = c;

	// A multi-plate file opens on its first plate, like OrcaSlicer: the preview
	// shows that plate, and the picker can switch it.
	const applyInspection = useCallback(
		(inspection: ThreeMfInspection) => {
			setPlateInfo(inspection);
			setPlateIndex(inspection.plates.length > 1 ? inspection.plates[0].index : null);
		},
		[setPlateIndex, setPlateInfo],
	);

	const handleFileSelected = useCallback(
		(selected: File) => {
			setFile(selected);
			setModelId(null);
			setUploadStatus('uploading');
			setScaleToastDismissed(false);
			setViewMode('model');
			setPlateInfo(null);
			setPlateIndex(null);
			setObjectThumbs({});
			setObjectPickerOpen(false);
			setPlacement(null);
			setCopies(1);
			setMeshReport(null);
			setMeshToastDismissed(false);
			uploadModel(selected)
				.then((res) => {
					setMeshReport(res.mesh_report ?? null);
					setModelId(res.model_id);
					setUploadStatus('done');
					// Always fetch (even for non-3mf uploads): the endpoint always
					// returns a shape (a synthetic single implicit plate for anything
					// that isn't a .3mf with real plate metadata), so the plate
					// picker/nozzle-assignment UI never need a separate "is this even
					// a 3mf" branch.
					getModelPlates(res.model_id)
						.then(applyInspection)
						.catch(() => setPlateInfo(null));
				})
				.catch(() => setUploadStatus('error'));
		},
		[
			applyInspection,
			setCopies,
			setMeshReport,
			setObjectThumbs,
			setViewMode,
			setUploadStatus,
			setScaleToastDismissed,
			setPlateInfo,
			setPlateIndex,
			setObjectPickerOpen,
			setPlacement,
			setModelId,
			setFile,
			setMeshToastDismissed,
		],
	);

	// Loads one of the built-in sample models (SettingsMenu's "Load a sample
	// model…") instead of a local upload. The model is created server-side
	// (routers/sample_models.py copies the bundled file into a fresh
	// model_id), so unlike handleFileSelected there's no File object already
	// in hand -- re-fetch the bytes into one via GET /models/{id}/file so the
	// rest of the app (viewer preview, scale-to-fit) works exactly the same
	// as it does for a local upload.
	const handleLoadSample = useCallback(
		(sampleId: string) => {
			setFile(null);
			setModelId(null);
			setUploadStatus('uploading');
			setScaleToastDismissed(false);
			setViewMode('model');
			setPlateInfo(null);
			setPlateIndex(null);
			setObjectThumbs({});
			setObjectPickerOpen(false);
			setPlacement(null);
			setCopies(1);
			setMeshReport(null);
			return loadSampleModel(sampleId)
				.then((res) => {
					setModelId(res.model_id);
					getModelPlates(res.model_id)
						.then(applyInspection)
						.catch(() => setPlateInfo(null));
					return downloadModelFile(res.model_id);
				})
				.then((downloaded) => {
					setFile(downloaded);
					setUploadStatus('done');
				})
				.catch((err: Error) => {
					setUploadStatus('error');
					throw err;
				});
		},
		[
			applyInspection,
			setCopies,
			setMeshReport,
			setPlacement,
			setViewMode,
			setUploadStatus,
			setScaleToastDismissed,
			setPlateInfo,
			setObjectThumbs,
			setPlateIndex,
			setObjectPickerOpen,
			setFile,
			setModelId,
		],
	);

	// Stable reference: Viewer's effect depends on this, and an inline arrow
	// function would make it re-run (tearing down/rebuilding the three.js
	// scene) on every unrelated App re-render.
	const handleDimensions = useCallback((dims: Dimensions | null) => setDimensions(dims), [setDimensions]);
	return { applyInspection, handleFileSelected, handleLoadSample, handleDimensions };
}
