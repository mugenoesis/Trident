import { useCallback, useEffect, useState } from 'react';
import {
	type BambuAccount,
	type BambuImportResult,
	connectBambuAccount,
	findBambuPrinters,
	getBambuCloud,
	getBambuSignInUrl,
	importBambuPrinters,
	installBambuPlugin,
} from '../api';

const wording = (err: Error) => err.message.replace(/^\d{3}\s+/, '');

/** EXPERIMENT: whether Bambu accounts can be used, and the sign-in: Bambu's plug-in fetched when missing, Bambu's page opened, the pasted address handed over. */
export function useBambuSignIn() {
	const [enabled, setEnabled] = useState(false);
	const [busy, setBusy] = useState<string | null>(null);
	const [problem, setProblem] = useState<string | null>(null);
	const [link, setLink] = useState<string | null>(null);
	const [account, setAccount] = useState<BambuAccount | null>(null);

	useEffect(() => {
		getBambuCloud()
			.then((status) => setEnabled(status.enabled))
			.catch(() => setEnabled(false));
	}, []);

	const signIn = useCallback(() => {
		// The tab is opened by the click itself so it is not blocked while the plug-in downloads; it is pointed at Bambu's page afterwards.
		const tab = window.open('', '_blank');
		if (tab) tab.opener = null;
		setProblem(null);
		setLink(null);
		setBusy("Getting Bambu's plug-in…");
		getBambuCloud()
			.then(async (status) => {
				if (!status.plugin?.installed) await installBambuPlugin();
			})
			.then(() => getBambuSignInUrl())
			.then(({ url }) => {
				if (tab) tab.location.href = url;
				else setLink(url);
			})
			.catch((err: Error) => {
				tab?.close();
				setProblem(wording(err));
			})
			.finally(() => setBusy(null));
	}, []);

	const connect = useCallback((address: string) => {
		setProblem(null);
		setAccount(null);
		setBusy("Asking Bambu's plug-in…");
		connectBambuAccount(address)
			.then(setAccount)
			.catch((err: Error) => setProblem(wording(err)))
			.finally(() => setBusy(null));
	}, []);

	return { enabled, busy, problem, link, account, signIn, connect };
}

/** Which printers of a connected account are chosen to add, the address typed for each, and adding them. */
export function useBambuPicker(account: BambuAccount | null, onAdded: () => void) {
	const [chosen, setChosen] = useState<Set<number>>(new Set());
	const [ips, setIps] = useState<Record<number, string>>({});
	const [outcome, setOutcome] = useState<BambuImportResult | null>(null);
	const [problem, setProblem] = useState<string | null>(null);
	const [busy, setBusy] = useState(false);
	const [searching, setSearching] = useState(false);

	useEffect(() => {
		// A new list starts with every printer Trident can add chosen, and the address found for each.
		const printers = account?.printers ?? [];
		setChosen(new Set(printers.filter((p) => p.supported).map((p) => p.index)));
		setIps(Object.fromEntries(printers.map((p) => [p.index, p.ip ?? ''])));
		setOutcome(null);
		setProblem(null);
	}, [account]);

	const toggle = useCallback((index: number) => {
		setChosen((prev) => {
			const next = new Set(prev);
			if (next.has(index)) next.delete(index);
			else next.add(index);
			return next;
		});
	}, []);

	const setIp = useCallback((index: number, value: string) => setIps((prev) => ({ ...prev, [index]: value })), []);

	const search = useCallback(
		(network: string) => {
			if (!account?.import_id) return;
			setSearching(true);
			setProblem(null);
			findBambuPrinters(account.import_id, network)
				.then((result) =>
					setIps((prev) => {
						const next = { ...prev };
						// An address already typed is never replaced by a found one.
						for (const printer of result.printers) if (printer.ip && !next[printer.index]) next[printer.index] = printer.ip;
						return next;
					}),
				)
				.catch((err: Error) => setProblem(wording(err)))
				.finally(() => setSearching(false));
		},
		[account],
	);

	const add = useCallback(() => {
		if (!account?.import_id) return;
		setBusy(true);
		setProblem(null);
		importBambuPrinters(
			account.import_id,
			[...chosen].map((index) => ({ index, ip: ips[index] ?? '' })),
		)
			.then((result) => {
				setOutcome(result);
				if (result.added.length > 0) onAdded();
			})
			.catch((err: Error) => setProblem(wording(err)))
			.finally(() => setBusy(false));
	}, [account, chosen, ips, onAdded]);

	return { chosen, ips, outcome, problem, busy, searching, toggle, setIp, search, add };
}
