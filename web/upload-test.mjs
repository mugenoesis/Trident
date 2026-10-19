// Browser test of the model upload box against a *running* container (see smoke-test.mjs for how to run it):
//   docker run --rm --network host -v "$(pwd):/work" -w /work mcr.microsoft.com/playwright:v1.64.0-noble npm run smoke:upload
//
// iPadOS Safari greys out .stl and .3mf in the file picker when the input lists extensions in `accept`, and a file dragged from
// the Files app must still reach the server as the `file` part of the multipart upload.

import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const BASE_URL = process.env.SMOKE_BASE_URL ?? 'http://localhost:8000';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
let failed = false;
const check = (ok, what) => {
	console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`);
	if (!ok) failed = true;
};

await page.goto(BASE_URL, { waitUntil: 'networkidle' });
const justMe = page.getByRole('button', { name: 'Just me (no login)' });
if (await justMe.isVisible().catch(() => false)) await justMe.click();
await page.waitForSelector('text=TridentSlicer');

const accept = await page.locator('input[data-model-input]').getAttribute('accept');
check(
	accept === null,
	`the model picker lists no file extensions in accept (got ${JSON.stringify(accept)}), so iPadOS does not grey out .stl/.3mf`,
);

const bytes = fs.readFileSync(path.resolve('fixtures/test-cube.stl')).toString('base64');
const uploaded = page.waitForResponse((r) => r.url().endsWith('/models') && r.request().method() === 'POST');
await page.evaluate(async (b64) => {
	const data = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
	const dt = new DataTransfer();
	dt.items.add(new File([data], 'dropped-cube.stl'));
	document.querySelector('.uploader').dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
}, bytes);
const response = await uploaded;
check(response.status() === 200, 'the server accepts the dropped file (it found the multipart `file` part)');
const stored = await response.json();
check(stored.filename === 'dropped-cube.stl', `the file keeps its name (got ${stored.filename})`);
await page.waitForSelector('text=Ready to slice', { timeout: 15000 });
check(true, 'the dropped file is ready to slice');

await browser.close();
process.exit(failed ? 1 : 0);
