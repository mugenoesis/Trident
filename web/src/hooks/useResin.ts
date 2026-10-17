import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createJob, deleteMyResin, getJob, getResinChoice, listResinPrinters, listResins, saveMyResin } from '../api';
import { ACTIVE_STATUSES, POLL_INTERVAL_MS } from '../appHelpers';
import {
	DEFAULT_RESIN_PROCESS,
	EMPTY_RESIN_VALUES,
	numericValues,
	packResinSettings,
	type ResinProcess,
	type ResinValues,
	resinOverrides,
	unpackResinSettings,
	valuesFromChoice,
} from '../resinSettings';
import type { JobRecord, PrinterRecord, ResinChoice, ResinInfo, ResinPrinterInfo } from '../types';
import { useResinLayers } from './useResinLayers';

export type Technology = 'fdm' | 'resin';

const TECHNOLOGY_KEY = 'trident.technology';

function storedTechnology(): Technology {
	try {
		return localStorage.getItem(TECHNOLOGY_KEY) === 'resin' ? 'resin' : 'fdm';
	} catch {
		return 'fdm';
	}
}

// Loads the resin printers and resins once, the first time resin mode is on.
function useResinCatalog(active: boolean) {
	const [printers, setPrinters] = useState<ResinPrinterInfo[]>([]);
	const [resins, setResins] = useState<ResinInfo[]>([]);
	const [catalogError, setCatalogError] = useState<string | null>(null);
	const loaded = useRef(false);
	useEffect(() => {
		if (!active || loaded.current) return;
		loaded.current = true;
		Promise.all([listResinPrinters(), listResins()])
			.then(([p, r]) => {
				setPrinters(p);
				setResins(r);
			})
			.catch((err: Error) => setCatalogError(err.message));
	}, [active]);
	const reloadResins = useCallback(() => listResins().then(setResins), []);
	return { printers, resins, catalogError, reloadResins };
}

// The resin's own values for the printer and layer height chosen, fetched when any of them changes (and so replacing edits made to the old ones).
function useResinChoice(printerName: string, resinName: string, layerHeight: string) {
	const [choice, setChoice] = useState<ResinChoice | null>(null);
	const [choiceError, setChoiceError] = useState<string | null>(null);
	const [values, setValues] = useState<ResinValues>(EMPTY_RESIN_VALUES);
	// Values restored from a saved printer: they win over the resin's own the first time its choice loads.
	const restored = useRef<ResinValues | null>(null);
	useEffect(() => {
		setChoice(null);
		setChoiceError(null);
		if (!printerName || !resinName) return;
		let stale = false;
		getResinChoice(resinName, printerName, Number(layerHeight))
			.then((c) => {
				if (stale) return;
				setChoice(c);
				setValues(restored.current ?? valuesFromChoice(c));
				restored.current = null;
			})
			.catch((err: Error) => {
				if (!stale) setChoiceError(err.message);
			});
		return () => {
			stale = true;
		};
	}, [printerName, resinName, layerHeight]);
	return { choice, choiceError, values, setValues, restored };
}

function useResinJob() {
	const [job, setJob] = useState<JobRecord | null>(null);
	const [sliceError, setSliceError] = useState<string | null>(null);
	const timer = useRef<ReturnType<typeof setInterval> | null>(null);
	const jobId = job?.id;
	const jobActive = job !== null && ACTIVE_STATUSES.includes(job.status);
	useEffect(() => {
		if (!jobId || !jobActive) return;
		timer.current = setInterval(() => {
			getJob(jobId)
				.then(setJob)
				.catch(() => {});
		}, POLL_INTERVAL_MS);
		return () => {
			if (timer.current) clearInterval(timer.current);
		};
	}, [jobId, jobActive]);
	return { job, setJob, sliceError, setSliceError };
}

// The resin side of the main screen: which printer and resin, the values to slice with, and the job that slices them.
export function useResin(modelId: string | null) {
	const [technology, setTechnologyState] = useState<Technology>(storedTechnology);
	const catalog = useResinCatalog(technology === 'resin');
	const [printerName, setPrinterName] = useState('');
	const [resinName, setResinName] = useState('');
	const [process, setProcess] = useState<ResinProcess>(DEFAULT_RESIN_PROCESS);
	const { choice, choiceError, values, setValues, restored } = useResinChoice(printerName, resinName, process.layerHeight);
	const { job, setJob, sliceError, setSliceError } = useResinJob();

	const setTechnology = useCallback((t: Technology) => {
		setTechnologyState(t);
		try {
			localStorage.setItem(TECHNOLOGY_KEY, t);
		} catch {
			// private mode: the choice just lasts until the page is closed
		}
	}, []);

	const printer = useMemo(() => catalog.printers.find((p) => p.name === printerName) ?? null, [catalog.printers, printerName]);
	const canSlice = Boolean(modelId && printer?.supported && !(job && ACTIVE_STATUSES.includes(job.status)));

	// Saves the values on screen as a resin of the user's own, and chooses it.
	const makeMyResin = useCallback(
		(name: string) =>
			saveMyResin({
				name,
				printer: printerName,
				layer_height: Number(process.layerHeight),
				settings: numericValues(values),
				based_on: resinName || null,
			}).then(async (info) => {
				await catalog.reloadResins();
				setResinName(info.name);
			}),
		[printerName, process.layerHeight, values, resinName, catalog],
	);

	const removeMyResin = useCallback(async () => {
		await deleteMyResin(resinName);
		await catalog.reloadResins();
		setResinName('');
	}, [resinName, catalog]);

	// What a saved resin printer keeps: the printer, its resin, and the slice settings as they are now.
	const settingsToSave = useCallback(() => packResinSettings(process, values), [process, values]);

	// Brings a saved resin printer back: switches to resin mode and restores its printer, resin and settings.
	const applySavedResinPrinter = useCallback(
		(saved: PrinterRecord) => {
			const { process: savedProcess, values: savedValues } = unpackResinSettings(saved.resin_settings);
			const resin = saved.filament_profiles[0] ?? '';
			const refetches = saved.machine_profile !== printerName || resin !== resinName || savedProcess.layerHeight !== process.layerHeight;
			if (savedValues) {
				setValues(savedValues);
				restored.current = refetches ? savedValues : null;
			}
			setTechnology('resin');
			setPrinterName(saved.machine_profile);
			setResinName(resin);
			setProcess(savedProcess);
		},
		[printerName, resinName, process.layerHeight, setValues, restored, setTechnology],
	);

	const slice = useCallback(() => {
		if (!modelId || !printerName) return;
		setSliceError(null);
		createJob({
			model_id: modelId,
			technology: 'resin',
			printer_profile: printerName,
			filament_profiles: resinName ? [resinName] : [],
			setting_overrides: resinOverrides(process, values),
		})
			.then(setJob)
			.catch((err: Error) => setSliceError(err.message));
	}, [modelId, printerName, resinName, process, values, setJob, setSliceError]);

	const layers = useResinLayers(job?.status === 'succeeded' ? job.id : null);

	return {
		technology,
		setTechnology,
		...catalog,
		printerName,
		setPrinterName,
		resinName,
		setResinName,
		printer,
		process,
		setProcess,
		choice,
		choiceError,
		values,
		setValues,
		job,
		sliceError,
		canSlice,
		slice,
		settingsToSave,
		applySavedResinPrinter,
		makeMyResin,
		removeMyResin,
		layers,
	};
}

export type ResinState = ReturnType<typeof useResin>;
