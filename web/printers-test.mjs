// Browser check of the Printers page (the live state of saved Klipper printers), against a *running* container. A fake Moonraker (an HTTP
// server in this process, whose state the test changes) is what the container talks to. Like smoke-test.mjs it needs Playwright's browsers:
//
//   docker run --rm --network host -v "$(pwd):/work" -w /work mcr.microsoft.com/playwright:v1.64.0-noble npm run smoke:printers
//
// SMOKE_BASE_URL (default http://localhost:8000) says where Trident is. KLIPPER_FAKE_HOST is the address the container reaches this
// machine on (default 172.17.0.1, Docker's bridge gateway). The container may be on its first-run screen.

import http from 'node:http';
import { chromium } from 'playwright';

const BASE_URL = process.env.SMOKE_BASE_URL ?? 'http://localhost:8000';
const FAKE_HOST = process.env.KLIPPER_FAKE_HOST ?? '172.17.0.1';
const fail = (message) => {
	throw new Error(message);
};
const check = (condition, message) => {
	if (!condition) fail(message);
	console.log(`   ok: ${message}`);
};

// ---- a Moonraker whose print the test steers ----
const PNG_1X1 = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');
const printer = { state: 'printing', file: 'part.gcode', progress: 0.25, duration: 600, message: '' };
const seen = { posts: [], gets: 0 };
const statusObjects = () => ({
	webhooks: { state: 'ready' },
	print_stats: {
		state: printer.state,
		filename: printer.file,
		print_duration: printer.duration,
		message: printer.message,
		info: { current_layer: 12, total_layer: 80 },
	},
	virtual_sdcard: { progress: printer.progress },
	extruder: { temperature: 214.8, target: 215 },
	heater_bed: { temperature: 59.9, target: 60 },
	'temperature_sensor chamber': { temperature: 31.4 },
});
const moonraker = http.createServer((req, res) => {
	const path = req.url.split('?')[0];
	seen.gets += req.method === 'GET' ? 1 : 0;
	const json = (body) => {
		res.setHeader('Content-Type', 'application/json');
		res.end(JSON.stringify(body));
	};
	if (req.method === 'POST' && path.startsWith('/printer/print/')) {
		const action = path.split('/').pop();
		seen.posts.push(action);
		return json({ result: 'ok' });
	}
	if (path === '/printer/objects/list')
		return json({
			result: { objects: ['webhooks', 'print_stats', 'virtual_sdcard', 'extruder', 'heater_bed', 'temperature_sensor chamber', 'fan'] },
		});
	if (path === '/printer/objects/query') return json({ result: { status: statusObjects() } });
	if (path === '/server/webcams/list')
		return json({ result: { webcams: [{ name: 'Toolhead', enabled: true, snapshot_url: '/cam.png', stream_url: '/cam' }] } });
	if (path === '/cam.png') {
		res.setHeader('Content-Type', 'image/png');
		return res.end(PNG_1X1);
	}
	res.statusCode = 404;
	res.end('{}');
});
await new Promise((resolve) => moonraker.listen(0, '0.0.0.0', resolve));
const fakeUrl = `http://${FAKE_HOST}:${moonraker.address().port}`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 1200 } });
const pageErrors = [];
page.on('pageerror', (err) => pageErrors.push(String(err)));

console.log(`[1/7] Saving printers (the fake Moonraker is at ${fakeUrl}) and opening the Printers page ...`);
await page.goto(BASE_URL, { waitUntil: 'networkidle' });
const justMe = page.getByRole('button', { name: 'Just me (no login)' });
if (await justMe.isVisible().catch(() => false)) await justMe.click();
await page.waitForSelector('text=Trident Studio');
const save = (name, host) =>
	page.evaluate(
		async ([n, h]) => {
			const body = {
				name: n,
				vendor: 'Custom',
				machine_profile: 'x',
				process_profile: 'x',
				...(h ? { host_type: 'moonraker', print_host: h } : {}),
			};
			const res = await fetch('/printers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
			return res.status;
		},
		[name, host],
	);
check((await save('Voron', fakeUrl)) === 200, 'a printer with a Klipper address is saved');
check((await save('Shed', 'http://127.0.0.1:1')) === 200, 'one that is off is saved');
check((await save('Marlin', null)) === 200, 'and one with no address at all');
await page.getByRole('button', { name: 'Printers', exact: true }).click();
const panel = page.getByRole('dialog', { name: 'Your printers' });
await panel.waitFor();
const card = (name) => panel.locator('.printer-card', { hasText: name });
await panel.locator('.printer-card').first().waitFor(); // the list of printers loads once the page is open
check((await panel.locator('.printer-card').count()) === 2, 'one card for each saved printer with a Klipper address');
check((await card('Marlin').count()) === 0, 'and none for a printer that has no address');

console.log('[2/7] A print under way ...');
const voron = card('Voron');
await voron.getByText('Printing', { exact: true }).waitFor({ timeout: 10000 });
check((await voron.getByText('part.gcode').count()) === 1, 'the file is named');
check((await voron.getByText('25%').count()) === 1, 'the progress is shown');
check((await voron.getByText('layer 12 of 80').count()) === 1, 'and the layers');
check((await voron.getByText(/30 min/).count()) >= 1, 'and the time left (a quarter done in ten minutes)');
check((await voron.getByText('214.8°').count()) === 1, 'the nozzle temperature is shown');
check((await voron.getByText('Chamber').count()) === 1, 'and the chamber');
check((await voron.getByRole('button', { name: 'Pause' }).count()) === 1, 'it can be paused');
check((await voron.getByRole('button', { name: 'Resume' }).count()) === 0, 'but not resumed');

console.log('[3/7] The webcam ...');
const cam = voron.locator('img.printer-cam');
await cam.waitFor({ timeout: 10000 });
check(
	/\/printers\/[^/]+\/webcams\/0\/snapshot/.test((await cam.getAttribute('src')) ?? ''),
	'the picture comes through the server, not from the printer',
);
check(await cam.evaluate((img) => img.complete && img.naturalWidth > 0), 'and it loads');

console.log('[4/7] A printer that is off ...');
const shed = card('Shed');
await shed.getByText('Offline', { exact: true }).waitFor({ timeout: 10000 });
check(/reach/i.test(await shed.innerText()), 'it says why it is offline');
check((await shed.getByRole('button', { name: /Pause|Resume|Cancel/ }).count()) === 0, 'and has no buttons for a print');

console.log('[5/7] Pausing ...');
await voron.getByRole('button', { name: 'Pause' }).click();
await page.waitForFunction(() => true);
check(
	await (async () => {
		for (let i = 0; i < 20 && !seen.posts.includes('pause'); i++) await page.waitForTimeout(250);
		return seen.posts.includes('pause');
	})(),
	'the printer was told to pause',
);
printer.state = 'paused';
await voron.getByText('Paused', { exact: true }).waitFor({ timeout: 10000 });
check((await voron.getByRole('button', { name: 'Resume' }).count()) === 1, 'it can then be resumed');
await voron.getByRole('button', { name: 'Resume' }).click();
check(
	await (async () => {
		for (let i = 0; i < 20 && !seen.posts.includes('resume'); i++) await page.waitForTimeout(250);
		return seen.posts.includes('resume');
	})(),
	'and the printer was told to resume',
);
printer.state = 'printing';
await voron.getByText('Printing', { exact: true }).waitFor({ timeout: 10000 });

console.log('[6/7] Cancelling asks first ...');
await voron.getByRole('button', { name: 'Cancel print…' }).click();
const confirm = page.getByRole('alertdialog', { name: /Cancel the print on Voron/ });
await confirm.waitFor();
check(/25%/.test(await confirm.innerText()) && /part\.gcode/.test(await confirm.innerText()), 'the question says what would be lost');
await confirm.getByRole('button', { name: 'Keep printing' }).click();
await confirm.waitFor({ state: 'detached' });
check(!seen.posts.includes('cancel'), 'keeping it tells the printer nothing');
await voron.getByRole('button', { name: 'Cancel print…' }).click();
await confirm.getByRole('button', { name: 'Cancel the print', exact: true }).click();
check(
	await (async () => {
		for (let i = 0; i < 20 && !seen.posts.includes('cancel'); i++) await page.waitForTimeout(250);
		return seen.posts.includes('cancel');
	})(),
	'confirming cancels it',
);
printer.state = 'error';
printer.message = 'Heater extruder not heating at expected rate';
await voron.getByText('Error', { exact: true }).waitFor({ timeout: 10000 });
check((await voron.getByText('Heater extruder not heating at expected rate').count()) === 1, 'an error shows the printer’s own message');

console.log('[7/7] Closing it stops the asking ...');
await panel.getByRole('button', { name: /Close/ }).click();
await panel.waitFor({ state: 'detached' });
const before = seen.gets;
await page.waitForTimeout(7000);
check(seen.gets === before, 'nothing is asked of the printers once the page is closed');

check(pageErrors.length === 0, `no page errors (${pageErrors.join('; ')})`);
await browser.close();
moonraker.close();
console.log('printers page browser check passed');
