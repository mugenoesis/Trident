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

console.log(`[1/11] Loading ${BASE_URL} ...`);
await page.goto(BASE_URL, { waitUntil: 'networkidle' });
const justMe = page.getByRole('button', { name: 'Just me (no login)' });
if (await justMe.isVisible()) await justMe.click();
await page.waitForSelector('text=TridentSlicer');

console.log('[2/11] Uploading a model, then switching to Resin ...');
await page.locator('input[type="file"]').setInputFiles(path.resolve('fixtures/test-cube.stl'));
await page.waitForSelector('text=Ready to slice', { timeout: 15000 });
const panel = page.locator('.panel-settings');
check((await panel.getByRole('button', { name: 'FDM', exact: true }).getAttribute('aria-pressed')) === 'true', 'FDM is the starting mode');
await panel.getByRole('button', { name: 'Resin', exact: true }).click();
check((await panel.getByRole('button', { name: 'Resin', exact: true }).getAttribute('aria-pressed')) === 'true', 'Resin mode is on');
check((await panel.getByText('Nozzle diameter').count()) === 0, 'the FDM settings are gone');

console.log('[3/11] Choosing a printer ...');
await panel.getByLabel('Printer vendor').selectOption({ label: 'Elegoo' });
await panel.getByLabel('Printer', { exact: true }).selectOption({ label: 'Mars 3' });
await panel.getByText('Writes').waitFor();
check(await panel.getByText(/Screen\s+\d+ × \d+ px over/).isVisible(), 'the screen is shown');
check(await panel.getByText(/Build height\s+\d+(\.\d+)? mm/).isVisible(), 'the build height is shown');
check(await panel.getByText(/Writes\s+\.ctb for the/).isVisible(), 'the file type is shown');

console.log('[4/11] Choosing a resin and reading its settings ...');
await panel.getByLabel('Resin vendor').selectOption({ label: 'Siraya Tech' });
await panel.getByLabel('Resin', { exact: true }).selectOption({ label: 'Easy Grey' });
await panel.getByText(/published settings for 0\.05 mm layers/).waitFor();
check(await panel.getByRole('link', { name: 'Source' }).isVisible(), 'the source of the settings is linked');
check((await panel.getByLabel('Exposure', { exact: true }).inputValue()) === '2', "the resin's exposure fills in");
check((await panel.getByLabel('Bottom exposure').inputValue()) === '20', "the resin's bottom exposure fills in");
await panel.getByLabel('Exposure', { exact: true }).fill('2.5');

console.log('[5/11] Slicing ...');
await panel.getByLabel('Supports', { exact: true }).selectOption({ label: 'None' });
await panel.getByLabel('Pad', { exact: true }).selectOption({ label: 'Off: model sits on supports' });
await panel.getByRole('button', { name: 'Slice' }).click();
await panel.getByText('Sliced', { exact: true }).waitFor({ timeout: 120000 });
check(await panel.getByText('Layers', { exact: true }).isVisible(), 'the layer count is shown');
check(await panel.getByText('Print time', { exact: true }).isVisible(), 'the print time is shown');
check(await panel.getByText('Resin', { exact: true }).last().isVisible(), 'the resin used is shown');
await panel.screenshot({ path: 'smoke-resin-result.png' });

console.log("[6/11] Downloading the printer's file ...");
const link = panel.getByRole('link', { name: /^Download .*\.ctb$/ });
const href = await link.getAttribute('href');
const res = await page.request.get(new URL(href, BASE_URL).toString());
check(res.ok(), 'the download works');
const bytes = await res.body();
check(bytes.length > 1000, `the file has content (${bytes.length} bytes)`);

console.log('[7/11] Back to FDM ...');
await panel.getByRole('button', { name: 'FDM', exact: true }).click();
await panel.getByText('Nozzle diameter').first().waitFor();
check(true, 'the FDM settings are back');

console.log('[8/11] Saving the resin setup as a printer ...');
await panel.getByRole('button', { name: 'Resin', exact: true }).click();
const saved = panel.locator('.saved-printers select');
await panel.getByRole('button', { name: 'Save current setup as printer…' }).click();
await panel.locator('.saved-printers form input').first().fill('Resin corner');
check((await panel.getByText('Connection (optional').count()) === 0, 'a resin printer is not asked for a G-code connection');
await panel.getByRole('button', { name: 'Save printer' }).click();
await saved.locator('optgroup[label="Resin"] option', { hasText: 'Resin corner · Resin' }).waitFor({ state: 'attached' });
check(true, 'it is listed under Resin');

console.log('[9/11] Choosing it again brings the saved values back ...');
await panel.getByLabel('Exposure', { exact: true }).fill('9');
await panel.getByRole('button', { name: 'FDM', exact: true }).click();
check((await saved.inputValue()) === '', 'switching to FDM leaves no resin printer selected');
await saved.selectOption({ label: 'Resin corner · Resin' });
check(
	(await panel.getByRole('button', { name: 'Resin', exact: true }).getAttribute('aria-pressed')) === 'true',
	'choosing it switches to Resin',
);
await panel.getByLabel('Exposure', { exact: true }).waitFor();
check((await panel.getByLabel('Printer', { exact: true }).inputValue()).length > 0, 'its printer is chosen');
await page.waitForFunction(() => document.querySelector('#resin-exposure_time')?.value === '2.5');
check(true, 'its saved exposure is back (2.5, not the 9 typed after saving)');

console.log('[10/11] After a reload ...');
await page.reload({ waitUntil: 'networkidle' });
await page.waitForSelector('text=TridentSlicer');
await panel.getByLabel('Printer', { exact: true }).waitFor();
check((await panel.locator('#resin-printer option:checked').textContent()) === 'Mars 3', 'the saved resin printer is selected again');

console.log('[11/11] Deleting it ...');
await panel.getByText('Manage saved printers').click();
await panel.getByRole('button', { name: 'Delete' }).first().click();
await page.waitForFunction(
	() => ![...document.querySelectorAll('.saved-printers option')].some((o) => o.textContent.includes('Resin corner')),
);
check(true, 'it is gone from the list');

await browser.close();
if (pageErrors.length) fail(`page errors: ${pageErrors.join('; ')}`);
console.log('resin browser check passed');
