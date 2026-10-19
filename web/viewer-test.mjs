// Browser check that the model preview draws a whole solid, also when the file's triangles are wound the wrong way
// (the slicer repairs that on load, and the preview must not show holes where it did). Uploads a cube with two sides
// wound inward (fixtures/test-cube.stl) and a correct one, and compares how much model each preview draws. Needs a
// *running* container and Playwright's browsers:
//
//   docker run --rm --network host -v "$(pwd):/work" -w /work \
//     mcr.microsoft.com/playwright:v1.64.0-noble npm run smoke:viewer
//
// SMOKE_BASE_URL (default http://localhost:8000) says where it is. The container may be on its first-run screen.

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';
import { goodCube } from './stl-fixtures.mjs';

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
await page.goto(BASE_URL, { waitUntil: 'networkidle' });
const justMe = page.getByRole('button', { name: 'Just me (no login)' });
if (await justMe.isVisible()) await justMe.click();
await page.waitForSelector('text=Trident Studio');

// How many pixels of the preview are the model's orange (the plate and background are grey).
async function modelPixels() {
	await page.waitForTimeout(800); // let three.js draw a frame
	const png = await page.locator('.viewer canvas').screenshot();
	return page.evaluate(async (b64) => {
		const img = new Image();
		img.src = `data:image/png;base64,${b64}`;
		await img.decode();
		const c = document.createElement('canvas');
		c.width = img.width;
		c.height = img.height;
		const ctx = c.getContext('2d');
		ctx.drawImage(img, 0, 0);
		const data = ctx.getImageData(0, 0, c.width, c.height).data;
		let n = 0;
		for (let i = 0; i < data.length; i += 4) if (data[i] > 90 && data[i] > data[i + 1] * 1.4 && data[i + 1] >= data[i + 2]) n++;
		return n;
	}, png.toString('base64'));
}

async function show(name, buffer) {
	await page.locator('input[type="file"]').setInputFiles({ name, mimeType: 'model/stl', buffer });
	await page.waitForSelector('text=Ready to slice', { timeout: 15000 });
}

console.log('[1/2] A correctly wound cube ...');
await show('good.stl', goodCube(20));
const good = await modelPixels();
check(good > 5000, `the preview draws the cube (${good} px)`);

console.log('[2/2] A cube with two sides wound inward ...');
await show('flipped.stl', readFileSync(path.resolve('fixtures/test-cube.stl')));
const flipped = await modelPixels();
check(Math.abs(flipped - good) / good < 0.05, `it draws as much as the correct one (${flipped} px against ${good} px)`);

await browser.close();
console.log('viewer browser check passed');
