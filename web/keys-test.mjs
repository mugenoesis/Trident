// Browser check of API keys and of opening a stored model from the address (`?model=<id>`), against a *running*
// container that has just been started (single-user mode is chosen here, so it must still be on the first-run
// screen). Like smoke-test.mjs it needs Playwright's browsers; run it in a container that has them:
//
//   docker run --rm --network host -v "$(pwd):/work" -w /work \
//     mcr.microsoft.com/playwright:v1.63.0-jammy npm run smoke:keys
//
// SMOKE_BASE_URL (default http://localhost:8000) says where it is.

import { readFileSync } from 'node:fs';
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
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

console.log(`[1/7] Loading ${BASE_URL} and choosing single-user mode ...`);
await page.goto(BASE_URL, { waitUntil: 'networkidle' });
await page.getByRole('button', { name: 'Just me (no login)' }).click();
await page.waitForSelector('text=TridentSlicer');

console.log('[2/7] Making an upload-only key ...');
await page.getByRole('button', { name: 'Settings' }).click();
await page.getByRole('button', { name: 'API keys…' }).click();
const panel = page.locator('.settings-panel');
await panel.getByLabel('Name', { exact: true }).fill('Holecraft');
await panel.locator('select').selectOption({ label: 'Holecraft: upload models only' });
await panel.getByRole('button', { name: 'Make key' }).click();
const secret = await panel.getByLabel('The new API key').inputValue();
check(secret.startsWith('trident_'), 'the key is shown once, and looks like a Trident key');
check(await panel.getByText('It cannot read, slice or delete anything.').isVisible(), 'it says what an upload-only key cannot do');
await panel.getByRole('button', { name: 'Done' }).click();
await panel.getByText('Uploads models only').waitFor();
check(await panel.getByText('Uploads models only').isVisible(), 'the list shows the key with its access');
check(!(await page.content()).includes(secret), 'the list does not show the secret again');

console.log('[3/7] Uploading with the key, and nothing else ...');
const upload = await page.request.post(`${BASE_URL}/models`, {
	headers: { Authorization: `Bearer ${secret}` },
	multipart: { file: { name: 'cube.stl', mimeType: 'model/stl', buffer: readFileSync(path.resolve('fixtures/test-cube.stl')) } },
});
check(upload.ok(), 'the key uploads a model');
const modelId = (await upload.json()).model_id;
const jobs = await page.request.get(`${BASE_URL}/jobs`, { headers: { Authorization: `Bearer ${secret}` } });
check(jobs.status() === 403, 'the same key may not list jobs');

console.log('[4/7] Opening the model from the address ...');
await page.goto(`${BASE_URL}/?model=${modelId}`, { waitUntil: 'networkidle' });
await page.waitForSelector('text=Ready to slice', { timeout: 15000 });
check(!page.url().includes('model='), 'the address no longer asks for the model (a reload will not open it again)');
check((await page.locator('.viewer canvas').count()) > 0, 'the model is in the viewer');

console.log('[5/7] Revoking the key ...');
await page.getByRole('button', { name: 'Settings' }).click();
await page.getByRole('button', { name: 'API keys…' }).click();
const second = page.locator('.settings-panel');
await second.getByRole('button', { name: 'Revoke' }).click();
await second.getByRole('button', { name: 'Really revoke?' }).click();
await second.getByText('Uploads models only').waitFor({ state: 'detached' });
const after = await page.request.post(`${BASE_URL}/models`, {
	headers: { Authorization: `Bearer ${secret}` },
	multipart: { file: { name: 'cube.stl', mimeType: 'model/stl', buffer: Buffer.from('x') } },
});
check(after.status() === 401, 'a revoked key stops working at once');

console.log('[6/7] A model that is not there ...');
await page.goto(`${BASE_URL}/?model=nosuchmodel`, { waitUntil: 'networkidle' });
await page.waitForSelector('text=TridentSlicer');
check(!page.url().includes('model='), 'a model that cannot be found still clears the address');

console.log("[7/7] A key for Holecraft's resin tools (hollow, supports) ...");
await page.goto(BASE_URL, { waitUntil: 'networkidle' });
await page.getByRole('button', { name: 'Settings' }).click();
await page.getByRole('button', { name: 'API keys…' }).click();
const third = page.locator('.settings-panel');
await third.getByLabel('Name', { exact: true }).fill('Holecraft resin tools');
await third.locator('select').selectOption({ label: 'Holecraft resin tools: upload models, hollow them, place supports' });
await third.getByRole('button', { name: 'Make key' }).click();
const hollowKey = await third.getByLabel('The new API key').inputValue();
check(
	await third
		.getByText('Access: uploads models, hollows them and places supports on them. It cannot read, slice or delete anything.')
		.isVisible(),
	'it says what a resin-tools key can do',
);
await third.getByRole('button', { name: 'Done' }).click();
await third.getByText('Uploads models, hollows them and places supports').waitFor();
check(await third.getByText('Uploads models, hollows them and places supports').isVisible(), 'the list shows its access');
const hollowJobs = await page.request.get(`${BASE_URL}/jobs`, { headers: { Authorization: `Bearer ${hollowKey}` } });
check(hollowJobs.status() === 403, 'a resin-tools key may not list jobs');
const hollowUpload = await page.request.post(`${BASE_URL}/models`, {
	headers: { Authorization: `Bearer ${hollowKey}` },
	multipart: { file: { name: 'cube.stl', mimeType: 'model/stl', buffer: readFileSync(path.resolve('fixtures/test-cube.stl')) } },
});
check(hollowUpload.ok(), 'a resin-tools key uploads a model');

await browser.close();
console.log('API keys check passed');
