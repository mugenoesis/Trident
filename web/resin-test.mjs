// Browser check of resin printing: switch to Resin, pick a printer and a resin, slice, and download the printer's file,
// against a *running* container whose engine has the resin catalogue and material library. Like smoke-test.mjs it needs
// Playwright's browsers; run it in a container that has them:
//
//   docker run --rm --network host -v "$(pwd):/work" -w /work \
//     mcr.microsoft.com/playwright:v1.64.0-noble npm run smoke:resin
//
// SMOKE_BASE_URL (default http://localhost:8000) says where it is. The container may be on its first-run screen.

import path from 'node:path';
import { chromium } from 'playwright';
import { goodCube } from './stl-fixtures.mjs';

// the model upload (the resin section has a file input of its own, for resin profiles)
const MODEL_INPUT = 'input[type="file"][data-model-input]';
const BASE_URL = process.env.SMOKE_BASE_URL ?? 'http://localhost:8000';
const fail = (message) => {
	throw new Error(message);
};
const check = (condition, message) => {
	if (!condition) fail(message);
	console.log(`   ok: ${message}`);
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 1100 } });
const pageErrors = [];
page.on('pageerror', (err) => pageErrors.push(String(err)));

// Chooses a printer and waits for the resin list that follows it (the list is for the printer chosen, and a resin it has no settings for is let go).
async function choosePrinter(vendor, model) {
	const panel = page.locator('.panel-settings');
	await panel.getByLabel('Printer vendor').selectOption({ label: vendor });
	const printer = panel.getByLabel('Printer', { exact: true });
	const listed = page.waitForResponse((r) => r.url().includes('/resin/resins?printer=') && r.ok(), { timeout: 3000 }).catch(() => null);
	await printer.selectOption({ label: model });
	await listed; // nothing comes when the printer was already the one chosen
	await page.waitForTimeout(200);
}

console.log(`[1/20] Loading ${BASE_URL} ...`);
await page.goto(BASE_URL, { waitUntil: 'networkidle' });
const justMe = page.getByRole('button', { name: 'Just me (no login)' });
if (await justMe.isVisible()) await justMe.click();
await page.waitForSelector('text=Trident Studio');

console.log('[2/20] Uploading a model, then switching to Resin ...');
await page.locator(MODEL_INPUT).setInputFiles(path.resolve('fixtures/test-cube.stl'));
await page.waitForSelector('text=Ready to slice', { timeout: 15000 });
const panel = page.locator('.panel-settings');
check((await panel.getByRole('button', { name: 'FDM', exact: true }).getAttribute('aria-pressed')) === 'true', 'FDM is the starting mode');
await panel.getByRole('button', { name: 'Resin', exact: true }).click();
check((await panel.getByRole('button', { name: 'Resin', exact: true }).getAttribute('aria-pressed')) === 'true', 'Resin mode is on');
check((await panel.getByText('Nozzle diameter').count()) === 0, 'the FDM settings are gone');

console.log('[3/20] Choosing a printer ...');
await choosePrinter('Elegoo', 'Mars 3');
await panel.getByText('Writes').waitFor();
check(await panel.getByText(/Screen\s+\d+ × \d+ px over/).isVisible(), 'the screen is shown');
check(await panel.getByText(/Build height\s+\d+(\.\d+)? mm/).isVisible(), 'the build height is shown');
check(await panel.getByText(/Writes\s+\.ctb for the/).isVisible(), 'the file type is shown');

console.log('[4/20] Choosing a resin and reading its settings ...');
await panel.getByLabel('Resin vendor').selectOption({ label: 'Siraya Tech' });
await panel.getByLabel('Resin', { exact: true }).selectOption({ label: 'Easy Grey' });
await panel.getByText(/published settings for 0\.05 mm layers/).waitFor();
check(await panel.getByRole('link', { name: 'Source' }).isVisible(), 'the source of the settings is linked');
check((await panel.getByLabel('Exposure', { exact: true }).inputValue()) === '2', "the resin's exposure fills in");
check((await panel.getByLabel('Bottom exposure').inputValue()) === '20', "the resin's bottom exposure fills in");
await panel.getByLabel('Exposure', { exact: true }).fill('2.5');

console.log('[5/20] Slicing ...');
await panel.getByLabel('Supports', { exact: true }).selectOption({ label: 'None' });
await panel.getByLabel('Pad', { exact: true }).selectOption({ label: 'Off: model sits on supports' });
await panel.getByRole('button', { name: 'Slice' }).click();
await panel.getByText('Sliced', { exact: true }).waitFor({ timeout: 120000 });
check(await panel.getByText('Layers', { exact: true }).isVisible(), 'the layer count is shown');
check(await panel.getByText('Print time', { exact: true }).isVisible(), 'the print time is shown');
check(await panel.getByText('Resin', { exact: true }).last().isVisible(), 'the resin used is shown');
await panel.screenshot({ path: 'smoke-resin-result.png' });
check((await panel.getByText('Cost', { exact: true }).count()) === 0, 'without a bottle price there is no cost');
await panel.getByLabel('Bottle price').fill('30');
await panel.getByLabel('Bottle size').fill('1000');
await panel.getByRole('button', { name: 'Slice' }).click();
const cost = panel.locator('.resin-stat', { hasText: 'Cost' });
await cost.waitFor({ timeout: 120000 });
const usedMl = Number.parseFloat(await panel.locator('.resin-stat', { hasText: 'Resin' }).locator('strong').textContent());
const costValue = Number.parseFloat(await cost.locator('strong').textContent());
check(Math.abs(costValue - (usedMl * 30) / 1000) < 0.01, `the cost is the resin used (${usedMl} ml) at the bottle price (${costValue})`);

console.log("[6/20] Downloading the printer's file ...");
const link = panel.getByRole('link', { name: /^Download .*\.ctb$/ });
const href = await link.getAttribute('href');
const res = await page.request.get(new URL(href, BASE_URL).toString());
check(res.ok(), 'the download works');
const bytes = await res.body();
check(bytes.length > 1000, `the file has content (${bytes.length} bytes)`);

console.log('[6b/20] Looking at the layers ...');
const slider = panel.getByLabel('Layer', { exact: true });
await slider.waitFor({ timeout: 60000 });
const layerImage = page.locator('.resin-layer-view img');
await layerImage.waitFor();
check(await panel.getByText(/Layer 1 of [\d,]+/).isVisible(), 'the slider says which layer, of how many');
check(
	await page.waitForFunction(() => document.querySelector('.resin-layer-view img')?.naturalWidth > 0).then(() => true),
	'the layer image loads',
);
const first = await layerImage.getAttribute('src');
await page.screenshot({ path: 'smoke-resin-layers.png' });
await slider.fill('50');
await panel.getByText(/Layer 51 of/).waitFor();
check((await layerImage.getAttribute('src')) !== first, 'moving the slider shows another layer');
await page.getByRole('button', { name: 'Back to model' }).click();
await page.waitForSelector('.viewer canvas');
check((await page.locator('.resin-layer-view').count()) === 0, 'Back to model returns to the model');

console.log('[6c/20] A layer too big to peel easily gets a warning ...');
check((await page.locator('.resin-warning').count()) === 0, 'a small model has no peel warning');
// a 50 mm cube: its largest layer is 5 x 5 cm = 25 cm2, over the limit
await page.locator(MODEL_INPUT).setInputFiles({ name: 'big.stl', mimeType: 'model/stl', buffer: goodCube(50) });
await page.waitForSelector('text=Ready to slice', { timeout: 15000 });
await panel.getByLabel('Layer height').selectOption({ label: '0.1 mm' });
await panel.getByRole('button', { name: 'Slice' }).click();
const warning = panel.locator('.resin-warning');
await warning.waitFor({ timeout: 120000 });
check(/large cross-section \(2\d\.\d cm²\)/.test(await warning.textContent()), 'the warning gives the area of the largest layer');
check((await panel.getByLabel('Bottle price').inputValue()) === '30', 'the bottle price stays when the layer height changes');
await panel.locator('.resin-stat', { hasText: 'Cost' }).waitFor();
check(true, 'so the next print has a cost too');
await panel.screenshot({ path: 'smoke-resin-peel.png' });

console.log('[7/20] Back to FDM ...');
await panel.getByRole('button', { name: 'FDM', exact: true }).click();
await panel.getByText('Nozzle diameter').first().waitFor();
check(true, 'the FDM settings are back');

console.log('[8/20] Saving the resin setup as a printer ...');
await panel.getByRole('button', { name: 'Resin', exact: true }).click();
// (the layer height was changed above, which brought back the resin's own exposure)
await panel.getByLabel('Exposure', { exact: true }).fill('2.5');
const saved = panel.locator('.saved-printers .field-group select');
await panel.getByRole('button', { name: 'Save current setup as printer…' }).click();
await panel.locator('.saved-printers form input').first().fill('Resin corner');
check((await panel.getByText('Connection (optional').count()) === 0, 'a resin printer is not asked for a G-code connection');
await panel.getByRole('button', { name: 'Save printer' }).click();
await saved.locator('optgroup[label="Resin"] option', { hasText: 'Resin corner · Resin' }).waitFor({ state: 'attached' });
check(true, 'it is listed under Resin');

console.log('[9/20] Choosing it again brings the saved values back ...');
await panel.getByLabel('Exposure', { exact: true }).fill('9');
// each change is remembered by its own request; let the first land before the second is made, as it would for a person
const cleared = page.waitForResponse(
	(r) => r.url().endsWith('/auth/last-selection') && (r.request().postData() ?? '').includes('"printer_id":null'),
);
await panel.getByRole('button', { name: 'FDM', exact: true }).click();
check((await saved.inputValue()) === '', 'switching to FDM leaves no resin printer selected');
await cleared;
// the choice is remembered by a request sent a moment after it is made; the reload below waits for the server to have it
const remembered = page.waitForResponse(
	(r) => r.url().endsWith('/auth/last-selection') && (r.request().postData() ?? '').includes('"printer_id":"'),
);
await saved.selectOption({ label: 'Resin corner · Resin' });
check(
	(await panel.getByRole('button', { name: 'Resin', exact: true }).getAttribute('aria-pressed')) === 'true',
	'choosing it switches to Resin',
);
await panel.getByLabel('Exposure', { exact: true }).waitFor();
check((await panel.getByLabel('Printer', { exact: true }).inputValue()).length > 0, 'its printer is chosen');
await page.waitForFunction(() => document.querySelector('#resin-exposure_time')?.value === '2.5');
check(true, 'its saved exposure is back (2.5, not the 9 typed after saving)');

console.log('[10/20] After a reload ...');
await remembered;
await page.reload({ waitUntil: 'networkidle' });
await page.waitForSelector('text=Trident Studio');
await panel.getByLabel('Printer', { exact: true }).waitFor();
// the last printer is restored once the saved printers have loaded, a moment after the page is up
await page.waitForFunction(() => document.querySelector('#resin-printer option:checked')?.textContent === 'Mars 3');
check(true, 'the saved resin printer is selected again');

console.log('[11/20] Deleting it ...');
await panel.getByText('Manage saved printers').click();
await panel.getByRole('button', { name: 'Delete' }).first().click();
await page.waitForFunction(
	() => ![...document.querySelectorAll('.saved-printers option')].some((o) => o.textContent.includes('Resin corner')),
);
check(true, 'it is gone from the list');

console.log('[12/20] Making my own resin from the values on screen ...');
await choosePrinter('Elegoo', 'Mars 3');
await panel.getByLabel('Resin vendor').selectOption({ label: 'Siraya Tech' });
await panel.getByLabel('Resin', { exact: true }).selectOption({ label: 'Easy Grey' });
await panel.getByText(/published settings for/).waitFor();
await panel.getByLabel('Exposure', { exact: true }).fill('3.7');
await panel.getByRole('button', { name: 'Make my own resin based on this config…' }).click();
await panel.getByLabel('Name of your resin').fill('My grey');
await panel.getByRole('button', { name: 'Save resin' }).click();
await panel.locator('#resin-resin option:checked').filter({ hasText: 'My grey' }).waitFor({ state: 'attached' });
check((await panel.getByLabel('Resin vendor').inputValue()) === 'My resins', 'it is listed under My resins and chosen');
await panel.getByText(/Using your own values/).waitFor();
check((await panel.getByLabel('Exposure', { exact: true }).inputValue()) === '3.7', 'it has the values that were on screen');

console.log('[13/20] Deleting it ...');
await panel.getByRole('button', { name: 'Delete my resin' }).click();
await page.waitForFunction(() => ![...document.querySelectorAll('#resin-resin-vendor option')].some((o) => o.textContent === 'My resins'));
check(true, 'it is gone from the list');

console.log('[14/20] Making a printer of my own from the Mars 3 ...');
await choosePrinter('Elegoo', 'Mars 3');
await panel.getByRole('button', { name: 'Copy as a custom printer…' }).click();
const form = panel.locator('.my-printer-form');
check(await form.getByLabel('Mirror the image left to right').isChecked(), 'a copied printer keeps its mirroring');
check((await form.getByLabel('Based on').inputValue()) === 'Elegoo Mars 3', 'it says which printer it is based on');
await form.getByLabel('Name', { exact: true }).fill('My Saturn');
await form.getByLabel('Screen width').fill('218.88');
await form.getByLabel('Screen height').fill('123.12');
await form.getByLabel('Pixels across').fill('3840');
await form.getByLabel('Pixels down').fill('3000');
await form.getByText(/not square/).waitFor();
check(await form.getByRole('button', { name: 'Save printer' }).isDisabled(), 'numbers that do not fit cannot be saved, and say why');
await form.getByLabel('Pixels down').fill('2160');
await form.getByText(/Pixel size 0\.0570/).waitFor();
check(await form.getByRole('button', { name: 'Save printer' }).isEnabled(), 'numbers that fit can be saved');
await form.getByLabel('Build height').fill('250');
await panel.screenshot({ path: 'smoke-resin-printer-form.png' });
await form.getByRole('button', { name: 'Save printer' }).click();
await form.waitFor({ state: 'detached' });
check((await panel.getByLabel('Printer vendor').inputValue()) === 'My printers', 'it is listed under My printers and chosen');
check(await panel.getByText(/Screen\s+3840 × 2160 px over 218\.88 × 123\.12 mm/).isVisible(), 'its screen is shown');
check(await panel.getByText(/Writes\s+\.ctb for the My Saturn/).isVisible(), 'its file type is shown');
await panel.getByLabel('Resin vendor').selectOption({ label: 'Siraya Tech' });
await panel.getByLabel('Resin', { exact: true }).selectOption({ label: 'Easy Grey' });
await panel.getByText(/published settings for/).waitFor();
check(true, 'a resin that publishes settings for the Mars 3 has them for it');
// (the page was reloaded in step 10, so the model has to be uploaded again)
await page.locator(MODEL_INPUT).setInputFiles({ name: 'small.stl', mimeType: 'model/stl', buffer: goodCube(20) });
await page.waitForSelector('text=Ready to slice', { timeout: 15000 });
await panel.getByRole('button', { name: 'Slice' }).click();
await panel.getByRole('link', { name: /^Download .*\.ctb$/ }).waitFor({ timeout: 180000 });
check(true, 'it slices for the new printer and offers its file');

console.log('[15/20] Changing it, then deleting it ...');
await panel.getByRole('button', { name: 'Edit my printer…' }).click();
await form.getByLabel('Build height').fill('260');
await form.getByRole('button', { name: 'Save printer' }).click();
await form.waitFor({ state: 'detached' });
check(await panel.getByText(/Build height\s+260 mm/).isVisible(), 'the change is saved');
await panel.getByRole('button', { name: 'Delete my printer' }).click();
await page.waitForFunction(
	() => ![...document.querySelectorAll('#resin-printer-vendor option')].some((o) => o.textContent === 'My printers'),
);
check(true, 'it is gone from the list');

console.log('[16/20] Importing a Chitubox resin profile ...');
const profile = [
	'currProfile:Test Blu 50um',
	'__resin:tough',
	'layerHeight:0.05',
	'normalExposureTime:15',
	'bottomLayExposureTime:65',
	'bottomLayCount:5',
	'normalLayerLiftHeight:10',
	'normalLayerLiftSpeed:48',
	'resinPrice:30',
	'resinUnit:$/L',
].join('\n');
await choosePrinter('Elegoo', 'Mars 3');
await panel.getByLabel('Resin vendor').selectOption({ label: 'Siraya Tech' });
await panel.getByLabel('Resin', { exact: true }).selectOption({ label: 'Easy Grey' });
await panel.getByText(/published settings for/).waitFor();
await page
	.locator('input[type="file"][accept=".cfg,.ini"]')
	.setInputFiles({ name: 'blu.cfg', mimeType: 'text/plain', buffer: Buffer.from(profile) });
await panel.getByText(/Imported 1 resin for Elegoo Mars 3/).waitFor();
check((await panel.getByLabel('Resin vendor').inputValue()) === 'My resins', 'the imported resin is listed under My resins and chosen');
await page
	.waitForFunction(
		() => [...document.querySelectorAll('label')].some((l) => l.textContent?.trim() === 'Exposure' && l.control?.value === '15'),
		null,
		{ timeout: 5000 },
	)
	.catch(() => {}); // the values follow the chosen resin a moment after the vendor does
check((await panel.getByLabel('Exposure', { exact: true }).inputValue()) === '15', 'it has the exposure of the profile');
check((await panel.getByLabel('Bottle price').inputValue()) === '30', 'and its price per litre as a bottle of 1000 ml');

console.log('[17/20] A file that is not a resin profile ...');
await page
	.locator('input[type="file"][accept=".cfg,.ini"]')
	.setInputFiles({ name: 'notes.cfg', mimeType: 'text/plain', buffer: Buffer.from('hello') });
await panel.getByText(/does not look like a Chitubox/).waitFor();
check(true, 'it says why it was not imported');
await panel.getByRole('button', { name: 'Delete my resin' }).click();

console.log('[18/20] A model sent with support points of its own ...');
const sent = await page.request.post(`${BASE_URL}/models`, {
	multipart: { file: { name: 'cube.stl', mimeType: 'model/stl', buffer: goodCube(20) } },
});
const sentId = (await sent.json()).model_id;
const stored = await page.request.put(`${BASE_URL}/models/${sentId}/support-points`, {
	data: {
		objects: [
			{
				points: [
					{ x: 5, y: 5, z: 0, radius: 0.4 },
					{ x: 15, y: 5, z: 0, radius: 0.4 },
					{ x: 10, y: 15, z: 0, radius: 0.5 },
				],
			},
		],
	},
});
check(stored.ok(), 'a model is stored with its support points');
await page.goto(`${BASE_URL}/?model=${sentId}`, { waitUntil: 'networkidle' });
await page.waitForSelector('text=Ready to slice', { timeout: 15000 });
await choosePrinter('Elegoo', 'Mars 3');
await panel.getByLabel('Resin vendor').selectOption({ label: 'Siraya Tech' });
await panel.getByLabel('Resin', { exact: true }).selectOption({ label: 'Easy Grey' });
await panel.getByText(/published settings for 0\.05 mm layers/).waitFor();
const handPlaced = panel.getByLabel('Use the 3 support points placed in Holecraft');
check(await handPlaced.isChecked(), 'it offers the 3 points, on by default');
await panel.getByRole('button', { name: 'Slice' }).click();
const pointStat = panel.locator('.resin-stat', { hasText: 'Support points' });
await pointStat.waitFor({ timeout: 180000 });
check((await pointStat.locator('strong').textContent()) === '3', 'the print was supported at exactly those 3 points');
await handPlaced.uncheck();
await panel.getByRole('button', { name: 'Slice' }).click();
await page.waitForFunction(
	() => {
		return Array.from(document.querySelectorAll('.resin-stat')).some(
			(s) => s.textContent?.includes('Support points') && s.querySelector('strong')?.textContent !== '3',
		);
	},
	null,
	{ timeout: 180000 },
);
check(true, 'with the box unticked the slicer places its own points');

console.log('[19/20] A printer is offered only the resins that have settings for it ...');
await page.goto(BASE_URL, { waitUntil: 'networkidle' });
await page.waitForSelector('text=Ready to slice', { timeout: 15000 }).catch(() => undefined);
await page.locator(MODEL_INPUT).setInputFiles(path.resolve('fixtures/test-cube.stl'));
await page.waitForSelector('text=Ready to slice', { timeout: 15000 });
await choosePrinter('Elegoo', 'Mars 3');
const resinVendors = async () => panel.getByLabel('Resin vendor').locator('option').allTextContents();
// the list follows the printer chosen a moment after it is chosen
const vendorOption = (text) => panel.getByLabel('Resin vendor').locator('option', { hasText: text });
await vendorOption('Siraya Tech').waitFor({ state: 'attached' });
await vendorOption('Anycubic').waitFor({ state: 'detached' });
const forMars = await resinVendors();
check(
	forMars.includes('Elegoo') && forMars.includes('Siraya Tech'),
	`a Mars 3 is offered Elegoo's and Siraya Tech's resins (${forMars.join(', ')})`,
);
check(!forMars.includes('Anycubic'), "and not Anycubic's, which have no settings for it");
await choosePrinter('Anycubic', 'Photon Mono');
await vendorOption('Anycubic').waitFor({ state: 'attached' });
await vendorOption('Elegoo').waitFor({ state: 'detached' });
const forMono = await resinVendors();
check(
	forMono.includes('Anycubic') && !forMono.includes('Elegoo'),
	`a Photon Mono is offered Anycubic's resins and not Elegoo's (${forMono.join(', ')})`,
);

console.log('[20/20] A resin with no settings for the printer is a starting point ...');
await page.goto(BASE_URL, { waitUntil: 'networkidle' });
await page.locator(MODEL_INPUT).setInputFiles(path.resolve('fixtures/test-cube.stl'));
await page.waitForSelector('text=Ready to slice', { timeout: 15000 });
await choosePrinter('Elegoo', 'Mars 3');
await panel.getByLabel('Also show resins with no settings for this printer').check();
await panel.getByLabel('Resin vendor').locator('option', { hasText: 'Anycubic' }).waitFor({ state: 'attached' });
await panel.getByLabel('Resin vendor').selectOption({ label: 'Anycubic' });
await panel.getByLabel('Resin', { exact: true }).selectOption({ label: 'High Speed Resin' });
await panel.getByText(/No settings for the Mars 3 yet/).waitFor();
check((await panel.getByLabel('Exposure', { exact: true }).inputValue()) === '', 'the exposure is left for the user');
check(
	((await panel.getByLabel('Exposure', { exact: true }).getAttribute('placeholder')) ?? '').includes('Photon'),
	"with the other printer's number as a hint",
);
check(await panel.getByRole('button', { name: 'Slice' }).isDisabled(), 'and it cannot be sliced until the exposure is given');
await panel.getByLabel('Exposure', { exact: true }).fill('2.5');
await panel.getByLabel('Bottom exposure').fill('30');
check(await panel.getByRole('button', { name: 'Slice' }).isEnabled(), 'it can once the exposures are typed');
await panel.getByRole('button', { name: 'Slice' }).click();
await panel.getByText('Sliced', { exact: true }).waitFor({ timeout: 180000 });
check(true, 'it slices with the values typed (the resin has no settings for this printer)');
await panel.getByRole('button', { name: 'Make my own resin based on this config…' }).click();
await panel.getByLabel('Name of your resin').fill('Mars 3 starting point');
await panel.getByRole('button', { name: 'Save resin' }).click();
await panel.getByLabel('Also show resins with no settings for this printer').uncheck();
await panel.getByLabel('Resin vendor').locator('option', { hasText: 'My resins' }).waitFor({ state: 'attached' });
check(true, 'saved, it is a resin of mine that fits the Mars 3 and is offered without the box ticked');

await browser.close();
if (pageErrors.length) fail(`page errors: ${pageErrors.join('; ')}`);
console.log('resin browser check passed');
