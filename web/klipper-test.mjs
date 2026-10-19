// Browser check of "Read it from a Klipper printer" in the New printer dialog, against a *running* container. A fake Moonraker
// (an HTTP server in this process, serving a printer shaped like a real toolchanger) is what the container reads. Like
// smoke-test.mjs it needs Playwright's browsers:
//
//   docker run --rm --network host -v "$(pwd):/work" -w /work mcr.microsoft.com/playwright:v1.64.0-noble npm run smoke:klipper
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

// ---- a Moonraker with a toolchanger's config: travel bigger than the bed, four extruders, a start macro with no parameters ----
const SETTINGS = {
	printer: { kinematics: 'corexy', max_velocity: 500, max_accel: 20000 },
	stepper_x: { position_min: 0, position_max: 271 },
	stepper_y: { position_min: 0, position_max: 335 },
	stepper_z: { position_min: -6, position_max: 275 },
	extruder: { nozzle_diameter: 0.4 },
	extruder1: { nozzle_diameter: 0.4 },
	extruder2: { nozzle_diameter: 0.4 },
	extruder3: { nozzle_diameter: 0.4 },
	bed_mesh: { mesh_min: [3, 3], mesh_max: [267, 267] },
	'gcode_macro print_start': { gcode: 'M84\nG92 E0' },
	'gcode_macro print_end': { gcode: 'M220 S100' },
};
const moonraker = http.createServer((req, res) => {
	const path = req.url.split('?')[0];
	const answers = {
		'/printer/info': { result: { state: 'ready', state_message: 'Printer is ready', hostname: 'lava', software_version: '1.5.2.13' } },
		'/printer/objects/query': { result: { status: { configfile: { settings: SETTINGS } } } },
		'/printer/objects/list': { result: { objects: ['extruder', 'bed_mesh'] } },
	};
	res.setHeader('Content-Type', 'application/json');
	res.statusCode = answers[path] ? 200 : 404;
	res.end(JSON.stringify(answers[path] ?? {}));
});
await new Promise((resolve) => moonraker.listen(0, '0.0.0.0', resolve));
const fakeUrl = `http://${FAKE_HOST}:${moonraker.address().port}`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 1600 } });
const pageErrors = [];
page.on('pageerror', (err) => pageErrors.push(String(err)));

console.log(`[1/6] Opening the New printer dialog (the fake Moonraker is at ${fakeUrl}) ...`);
await page.goto(BASE_URL, { waitUntil: 'networkidle' });
const justMe = page.getByRole('button', { name: 'Just me (no login)' });
if (await justMe.isVisible().catch(() => false)) await justMe.click();
await page.waitForSelector('text=Trident Studio');
// The section starts open on a fresh container and closed once a printer is chosen.
const newPrinter = page.getByRole('button', { name: /New printer/ }).first();
await newPrinter.waitFor({ timeout: 8000 }).catch(() => undefined); // it appears once the profile list has loaded
if (!(await newPrinter.isVisible())) await page.getByText(/^Printer settings/).click();
await newPrinter.click();
const dialog = page.getByRole('dialog', { name: 'New printer' });
await dialog.waitFor();
await dialog.getByText('Read it from a Klipper printer').waitFor();
check(await dialog.getByLabel('Printer address').isVisible(), 'the dialog has a section to read a Klipper printer, with an address box');
check(await dialog.getByLabel(/API key/).isVisible(), 'and an API key box');
check(await dialog.getByRole('button', { name: 'Read printer’s settings' }).isDisabled(), 'the button waits for an address');

// Not exact: a label that carries a tag also holds the tag's words.
const value = (label) => dialog.getByLabel(label).inputValue();
const tagOf = (label) => dialog.locator(`label:has-text("${label}") .field-tag`);

console.log('[2/6] Reading the printer ...');
await dialog.getByLabel('Printer address').fill(fakeUrl);
await dialog.getByRole('button', { name: 'Read printer’s settings' }).click();
await dialog.getByText(/Read “lava”/).waitFor();
check((await dialog.getByLabel('Name', { exact: true }).inputValue()) === 'lava', 'the name is the printer’s hostname');
check((await value('Width (X, mm)')) === '271', 'the width is read from the steppers');
check((await value('Depth (Y, mm)')) === '335', 'and the depth');
check((await value('Max height (Z, mm)')) === '275', 'and the height');
check((await value('Nozzle (mm)')) === '0.4', 'the nozzle');
check((await value('Max speed (mm/s)')) === '500', 'the speed');
check((await value('Max acceleration (mm/s²)')) === '20000', 'the acceleration');
check((await dialog.getByLabel('G-code flavour').inputValue()) === 'klipper', 'the firmware is Klipper');
check((await dialog.getByLabel('End G-code').inputValue()) === 'PRINT_END', 'the end G-code is the printer’s end macro');

console.log('[3/6] What to check ...');
const notes = dialog.locator('.klipper-notes');
check((await notes.locator('li').count()) === 3, 'three things are worth checking');
check(/335 mm along Y/.test(await notes.innerText()), 'the travel against the bed mesh is one');
check(/4 extruders/.test(await notes.innerText()), 'the four extruders are one');
check(/print_start macro takes no temperatures/.test(await notes.innerText()), 'a start macro with no temperatures is one');
check((await tagOf('Depth (Y, mm)').getAttribute('data-tag')) === 'check', 'the depth is marked to check');
check((await tagOf('Max height (Z, mm)').getAttribute('data-tag')) === 'check', 'and so is the height');
check((await tagOf('Width (X, mm)').getAttribute('data-tag')) === 'ok', 'the width says it is from the printer');
check((await tagOf('Nozzle (mm)').count()) === 1, 'so does the nozzle');
const sources = dialog.locator('.klipper-sources');
check((await sources.getByText('stepper_x position 0 to 271').count()) === 1, 'each value says where it was read');

console.log('[4/6] Changing a value ...');
await dialog.getByLabel('Width (X, mm)').fill('270');
check((await tagOf('Width (X, mm)').count()) === 0, 'a value that is typed over loses its “from printer” tag');
check((await tagOf('Depth (Y, mm)').count()) === 1, 'the others keep theirs');

console.log('[5/6] A printer that cannot be reached ...');
await dialog.getByLabel('Printer address').fill('http://127.0.0.1:1');
await dialog.getByRole('button', { name: /Read/ }).click();
await dialog.getByText(/Couldn't reach the printer/).waitFor();
check((await value('Width (X, mm)')) === '270', 'the form is left as it was');
check((await dialog.getByText(/Read “lava”/).count()) === 0, 'the success message is gone');

console.log('[6/6] Saving ...');
// The start G-code is left to the user when the printer's start macro takes no temperatures, and a generic printer has none to start from.
await dialog.getByLabel('Start G-code').fill('PRINT_START');
await dialog.getByRole('button', { name: 'Save printer' }).click();
await dialog
	.waitFor({ state: 'detached', timeout: 8000 })
	.catch(async () => fail(`the dialog stayed open: ${(await dialog.locator('.banner-error').allInnerTexts()).join(' | ')}`));
const stored = await page.evaluate(async () => (await fetch('/stored-profiles/machine/lava')).json());
check(stored.gcode_flavor === 'klipper', 'the saved printer is a Klipper one');
check(stored.printable_height === '275', 'with the height read');
check(stored.machine_end_gcode === 'PRINT_END', 'and the end macro');
check(
	JSON.stringify(stored.printable_area) === JSON.stringify(['0x0', '270x0', '270x335', '0x335']),
	'and the bed typed over the read one',
);

check(pageErrors.length === 0, `no page errors (${pageErrors.join('; ')})`);
await browser.close();
moonraker.close();
console.log('klipper import browser check passed');
