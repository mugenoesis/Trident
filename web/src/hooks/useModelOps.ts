import { useCallback } from 'react';
import { arrangeModel, downloadModelFile, getModelPlates, orientModel, transformModel, transformObjects } from '../api';
import type { ObjectEdit, Placement, TransformStep } from '../types';
import type { AppState, MainAppProps } from './useAppState';
import type { useModelUpload } from './useModelUpload';

export function useModelOps(c: AppState & Pick<MainAppProps, never> & ReturnType<typeof useModelUpload>) {
	const {
		modelId,
		printerName,
		processName,
		setPositionBusy,
		applyInspection,
		setFile,
		setModelId,
		setViewMode,
		setPlacement,
		plateIndex,
		setPlateIndex,
	} = c;

	// Auto-orient / Auto-arrange: the slicer's own helpers run server-side and
	// produce a new .3mf, which replaces the loaded model. After an arrange the
	// sliders show where it put the model; after an orient the position goes
	// back to the slicer's default.
	const runModelOp = useCallback(
		(op: 'orient' | 'arrange') => {
			if (!modelId || !printerName || !processName) return;
			setPositionBusy(op);
			const request = op === 'orient' ? orientModel(modelId, printerName, processName) : arrangeModel(modelId, printerName, processName);
			request
				.then(async (res) => {
					const [downloaded, inspection] = await Promise.all([downloadModelFile(res.model_id), getModelPlates(res.model_id)]);
					applyInspection(inspection);
					setFile(downloaded);
					setModelId(res.model_id);
					setViewMode('model');
					const objs = inspection.objects ?? [];
					if (op === 'arrange' && objs.length > 0) {
						const minX = Math.min(...objs.map((o) => o.center_x_mm - o.width_mm / 2));
						const maxX = Math.max(...objs.map((o) => o.center_x_mm + o.width_mm / 2));
						const minY = Math.min(...objs.map((o) => o.center_y_mm - o.depth_mm / 2));
						const maxY = Math.max(...objs.map((o) => o.center_y_mm + o.depth_mm / 2));
						setPlacement({ x: (minX + maxX) / 2, y: (minY + maxY) / 2 });
					} else {
						setPlacement(null);
					}
				})
				.catch((err: Error) => alert(`Could not ${op === 'orient' ? 'orient' : 'arrange'} the model: ${err.message}`))
				.finally(() => setPositionBusy(null));
		},
		[modelId, printerName, processName, applyInspection, setFile, setPlacement, setViewMode, setModelId, setPositionBusy],
	);

	// Rotate / stand the model on a face with the slicer (RotateMoveDialog), swap the
	// result in the way auto-orient does, and keep the position the user chose.
	const handleTransformModel = useCallback(
		async (steps: TransformStep[], position: Placement): Promise<boolean> => {
			if (!modelId) return false;
			try {
				const res = await transformModel(modelId, steps);
				const [downloaded, inspection] = await Promise.all([downloadModelFile(res.model_id), getModelPlates(res.model_id)]);
				applyInspection(inspection);
				setFile(downloaded);
				setModelId(res.model_id);
				setViewMode('model');
				setPlacement(position);
				return true;
			} catch (err) {
				alert(`Could not turn the model: ${(err as Error).message}`);
				return false;
			}
		},
		[modelId, applyInspection, setModelId, setFile, setPlacement, setViewMode],
	);

	// Turn and move the objects of a multi-object file one by one (RotateMoveDialog). The new model
	// keeps each object where it was put, so the group's centre is read back from it.
	const handleTransformObjects = useCallback(
		async (edits: ObjectEdit[], groupCentre: Placement): Promise<boolean> => {
			if (!modelId) return false;
			try {
				const res = await transformObjects(modelId, edits);
				const [downloaded, inspection] = await Promise.all([downloadModelFile(res.model_id), getModelPlates(res.model_id)]);
				applyInspection(inspection);
				// applyInspection goes back to the first plate; the user is still working on this one.
				if (inspection.plates.length > 1 && inspection.plates.some((p) => p.index === plateIndex)) setPlateIndex(plateIndex);
				setFile(downloaded);
				setModelId(res.model_id);
				setViewMode('model');
				const listed = inspection.objects ?? [];
				if (inspection.plates.length > 1) {
					// Plates keep the file's own coordinates; there is no group position to keep.
				} else if (listed.length > 0) {
					// Measured the way the server measures it when it places the group, so the job moves nothing.
					const minX = Math.min(...listed.map((o) => o.center_x_mm - o.width_mm / 2));
					const maxX = Math.max(...listed.map((o) => o.center_x_mm + o.width_mm / 2));
					const minY = Math.min(...listed.map((o) => o.center_y_mm - o.depth_mm / 2));
					const maxY = Math.max(...listed.map((o) => o.center_y_mm + o.depth_mm / 2));
					setPlacement({ x: (minX + maxX) / 2, y: (minY + maxY) / 2 });
				} else {
					setPlacement(groupCentre);
				}
				return true;
			} catch (err) {
				alert(`Could not turn the objects: ${(err as Error).message}`);
				return false;
			}
		},
		[modelId, applyInspection, plateIndex, setPlateIndex, setFile, setPlacement, setViewMode, setModelId],
	);
	return { runModelOp, handleTransformModel, handleTransformObjects };
}
