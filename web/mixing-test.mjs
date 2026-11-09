// Browser check of mixed colours: define a mix of two loaded filaments, see its estimated colour, find mixes for a wanted colour, give a
// colour of the model to the mix, slice, and confirm the printer's file prints with the mix's filaments only. Like smoke-test.mjs it needs
// Playwright's browsers and a *running* container with the engine (an ephemeral one, never the real Trident):
//
//   docker run --rm --network host -v "$(pwd):/work" -w /work -e SMOKE_BASE_URL=http://localhost:8333 \
//     mcr.microsoft.com/playwright:v1.64.1-noble npm run smoke:mixing
//
// SMOKE_BASE_URL (default http://localhost:8000) says where it is. The container may be on its first-run screen.

import path from 'node:path';
import { chromium } from 'playwright';

const BASE_URL = process.env.SMOKE_BASE_URL ?? 'http://localhost:8000';
const PRINTER = 'Snapmaker U1 (0.4 nozzle)';
const MATERIAL = 'Snapmaker PLA Basic @U1';
const fail = (message) => {
	throw new Error(message);
};
const check = (condition, message) => {
	if (!condition) fail(message);
	console.log(`   ok: ${message}`);
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 1200 } });
const pageErrors = [];
page.on('pageerror', (err) => pageErrors.push(String(err)));
const panel = page.locator('.panel-settings');
const mixes = panel.locator('.settings-collapsible', { hasText: 'Mixed colours' });
const assignment = page.locator('.nozzle-assignment select').first();
const slice = page.locator('button.slice-button');

console.log(`[1/11] Loading ${BASE_URL}, uploading a model, choosing the ${PRINTER} ...`);
await page.goto(BASE_URL, { waitUntil: 'networkidle' });
const justMe = page.getByRole('button', { name: 'Just me (no login)' });
if (await justMe.isVisible()) await justMe.click();
await page.waitForSelector('text=Trident Studio');
await page.locator('input[type="file"]').first().setInputFiles(path.resolve('fixtures/test-cube.stl'));
await page.waitForSelector('text=Ready to slice', { timeout: 15000 });
await panel.getByLabel('Printer vendor').selectOption({ label: 'Snapmaker' });
await panel.getByLabel('Printer (nozzle size shown in name)').selectOption({ label: PRINTER });
await page.waitForTimeout(1500);

console.log('[2/11] Four filament slots, each with a material ...');
const slotRows = panel.locator('.filament-slot-row');
while ((await slotRows.count()) < 4) await panel.getByRole('button', { name: '+ Add material slot' }).click();
for (let i = 0; i < 4; i++) await slotRows.nth(i).locator('select[size]').selectOption({ label: MATERIAL });
check((await slotRows.count()) === 4, 'there are four slots');

console.log('[3/11] The Mixed colours section starts empty ...');
await mixes.locator('summary').click();
check((await mixes.locator('.mix-card').count()) === 0, 'no mixes yet');
check(await mixes.getByRole('button', { name: '+ Add a mixed colour' }).isEnabled(), 'a mix can be added');
await mixes.getByRole('button', { name: '+ Add a mixed colour' }).click();
check(await mixes.getByRole('button', { name: 'Add mix' }).isDisabled(), 'with no filament picked the mix cannot be added');

console.log('[4/11] Picking blue and yellow shows the estimated colour ...');
await mixes.getByRole('button', { name: 'Slot 3 · Blue' }).click();
check(await mixes.getByText('Pick at least two filaments').isVisible(), 'one filament is not enough');
await mixes.getByRole('button', { name: 'Slot 4 · Yellow' }).click();
await mixes
	.locator('.mix-result-text b')
	.filter({ hasText: /^#[0-9A-F]{6}$/ })
	.waitFor();
const estimated = await mixes.locator('.mix-result-text b').textContent();
const reference = await page.request.post(`${BASE_URL}/mixes/preview`, {
	data: { colours: ['#ffffff', '#e0301e', '#0a84ff', '#ffd60a'], mixes: [{ components: [3, 4], weights: [1, 1] }] },
});
check(estimated === (await reference.json()).colours[0], `the colour shown (${estimated}) is the server's mixer's`);
await mixes.getByRole('button', { name: 'Slot 1 · White' }).click();
check(await mixes.getByRole('button', { name: 'Slot 2 · Red' }).isDisabled(), 'with three picked a fourth is refused');
await mixes.getByRole('button', { name: 'Slot 1 · White' }).click();
check((await mixes.locator('.mix-weight-row').count()) === 2, 'a share slider for each of the two');
await mixes.getByRole('button', { name: 'Add mix' }).click();
check((await mixes.locator('.mix-card').count()) === 1, 'the mix is added as a card');
check(await mixes.getByText('Blue 50% + Yellow 50%').isVisible(), 'which names its filaments and shares');
check(await mixes.getByText('Slot 5 · mix').isVisible(), 'and is slot 5');

console.log('[5/11] Finding mixes for a wanted colour ...');
await mixes.getByRole('button', { name: '+ Add a mixed colour' }).click();
await mixes.getByLabel('Wanted colour').fill('#4caf50');
await mixes.getByRole('button', { name: 'Find mixes' }).click();
const suggestions = mixes.locator('.mix-suggestion');
await suggestions.first().waitFor();
check((await suggestions.count()) === 4, 'four suggestions');
check(/difference \d/.test((await suggestions.first().textContent()) ?? ''), 'each says how close it is');
await suggestions.first().click();
check((await mixes.locator('.mix-pick.on').count()) >= 2, 'picking one fills the editor');
await mixes.getByRole('button', { name: 'Cancel' }).click();
check((await mixes.locator('.mix-card').count()) === 1, 'cancelling adds nothing');

console.log('[6/11] The mix is one more slot for the model ...');
check(
	(await assignment.locator('option', { hasText: 'Slot 5 (mix: Blue 50% + Yellow 50%)' }).count()) === 1,
	'the colour dropdown offers it',
);
check((await assignment.locator('option').count()) === 6, 'after the four filaments (and the prompt)');
await assignment.selectOption({ label: 'Slot 5 (mix: Blue 50% + Yellow 50%)' });

console.log('[7/11] Slicing sends the mix and prints with its filaments only ...');
const sent = page.waitForRequest((r) => r.url().endsWith('/jobs') && r.method() === 'POST');
await slice.click();
const body = (await sent).postDataJSON();
check(JSON.stringify(body.mixed_filaments) === JSON.stringify([{ components: [3, 4], weights: [50, 50] }]), 'the request carries the mix');
check(body.mixed_sublayers === false, 'with whole layers alternating');
check(body.filament_profiles.length === 4 && body.filament_profiles.every((p) => p === MATERIAL), 'and the four physical materials');
check(body.setting_overrides.remap_filament_extruder === '1:5', 'and the model goes on slot 5');
await page.waitForSelector('.status-succeeded, .status-failed', { timeout: 120000 });
check((await page.locator('.status-badge').first().textContent()) === 'succeeded', 'the slice succeeds');
const jobs = await (await page.request.get(`${BASE_URL}/jobs`)).json();
const gcode = await (await page.request.get(`${BASE_URL}/jobs/${jobs[0].id}/gcode`)).text();
const tools = new Set([...gcode.matchAll(/^T(\d+)\s*$/gm)].map((m) => Number(m[1])));
check(
	tools.has(2) && tools.has(3) && !tools.has(0) && !tools.has(1) && !tools.has(4),
	`only nozzles 3 and 4 print (saw ${[...tools].sort()})`,
);

console.log('[8/11] Changing the sub-layer choice counts as a change ...');
check(await slice.isDisabled(), 'the same settings are not sliced twice');
await mixes.getByLabel('Blend inside every layer').check();
check(await slice.isEnabled(), 'blending inside layers can be sliced again');
await mixes.getByLabel('Blend inside every layer').uncheck();

console.log('[9/11] Removing the mix lets go of the colour it was given ...');
await page.getByRole('button', { name: 'Back to 3D view' }).click(); // the assignment is on the model view, not the G-code view
check((await assignment.locator('option', { hasText: 'mix:' }).count()) === 1, 'the dropdown offers the mix before it is removed');
await mixes.getByRole('button', { name: 'Remove mix 1' }).click();
check((await mixes.locator('.mix-card').count()) === 0, 'the card is gone');
check((await assignment.locator('option', { hasText: 'mix:' }).count()) === 0, 'and the dropdown no longer offers it');
check(await slice.isDisabled(), 'and the colour is unassigned, so there is nothing to slice yet');

console.log('[10/11] A mix no part uses leaves the print as it was ...');
await mixes.getByRole('button', { name: '+ Add a mixed colour' }).click();
await mixes.getByRole('button', { name: 'Slot 3 · Blue' }).click();
await mixes.getByRole('button', { name: 'Slot 4 · Yellow' }).click();
await mixes.getByRole('button', { name: 'Add mix' }).click();
check((await mixes.locator('.mix-card').count()) === 1, 'a mix is there');
await assignment.selectOption({ label: `Slot 1 (White) — ${MATERIAL}` });
const sentUnused = page.waitForRequest((r) => r.url().endsWith('/jobs') && r.method() === 'POST');
await slice.click();
const unused = (await sentUnused).postDataJSON();
check(unused.filament_profiles.length === 4, 'the four physical materials are sent, as the mix names them by slot');
check(!('remap_filament_extruder' in unused.setting_overrides), 'and the model stays on slot 1');
await page.waitForSelector('.status-succeeded, .status-failed', { timeout: 120000 });
check((await page.locator('.status-badge').first().textContent()) === 'succeeded', 'the slice succeeds');

console.log('[11/11] A different number of filaments clears the mixes ...');
await panel.getByRole('button', { name: '+ Add material slot' }).click();
check((await mixes.locator('.mix-card').count()) === 0, 'adding a filament slot clears it');

await browser.close();
check(pageErrors.length === 0, `no page errors${pageErrors.length ? `: ${pageErrors.join(' | ')}` : ''}`);
console.log('All mixed colour browser checks passed.');
