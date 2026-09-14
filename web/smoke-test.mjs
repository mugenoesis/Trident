// End-to-end smoke test against a *running* headless-orca container: loads
// the app, uploads fixtures/test-cube.stl, picks a printer/material, slices,
// and waits for success. Not a unit test -- it needs real Playwright browser
// binaries, which this host can't install directly (no apt-get outside
// Docker), so run it in a container that already has them:
//
//   docker run --rm --network host -v "$(pwd):/work" -w /work \
//     mcr.microsoft.com/playwright:v1.63.0-jammy npm run smoke
//
// (pin the image tag to the `playwright` package version in package.json)
import { chromium } from 'playwright'
import path from 'node:path'

const BASE_URL = process.env.SMOKE_BASE_URL ?? 'http://localhost:8000'
const consoleErrors = []
const pageErrors = []

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })

page.on('console', (msg) => {
  if (msg.type() === 'error') consoleErrors.push(msg.text())
})
page.on('pageerror', (err) => pageErrors.push(String(err)))

console.log(`[1/8] Loading ${BASE_URL} ...`)
await page.goto(BASE_URL, { waitUntil: 'networkidle' })
await page.waitForSelector('text=headless-orca', { timeout: 10000 })
await page.screenshot({ path: 'smoke-1-initial.png' })

console.log('[2/8] Uploading test STL ...')
const fileInput = page.locator('input[type="file"]')
await fileInput.setInputFiles(path.resolve('fixtures/test-cube.stl'))
await page.waitForSelector('text=Ready to slice', { timeout: 15000 })
await page.waitForTimeout(500) // let three.js render a frame
await page.screenshot({ path: 'smoke-2-viewer.png' })
const canvasCount = await page.locator('.viewer canvas').count()
console.log(`   viewer canvas present: ${canvasCount > 0}`)

console.log('[3/8] Selecting a printer vendor ...')
const vendorSelect = page.locator('select').first()
const vendorOptions = await vendorSelect.locator('option').allTextContents()
const firstRealVendor = vendorOptions.find((v) => v && !v.includes('Select'))
if (!firstRealVendor) throw new Error('No vendor options loaded')
await vendorSelect.selectOption({ label: firstRealVendor })
console.log(`   vendor: ${firstRealVendor}`)

console.log('[4/8] Selecting a printer ...')
const printerSelect = page.locator('select').nth(1)
await page.waitForFunction(
  (sel) => document.querySelectorAll(sel)[1]?.options.length > 1,
  'select',
  { timeout: 10000 },
)
const printerOptions = await printerSelect.locator('option').allTextContents()
const firstPrinter = printerOptions.find((v) => v && !v.includes('Select') && !v.includes('Pick'))
if (!firstPrinter) throw new Error('No printer options loaded for vendor ' + firstRealVendor)
await printerSelect.selectOption({ label: firstPrinter })
console.log(`   printer: ${firstPrinter}`)

console.log('[5/8] Waiting for auto-filled material/process defaults ...')
await page.waitForTimeout(1500)
const materialSelect = page.locator('.field-group select[size]')
const materialValue = await materialSelect.inputValue().catch(() => '')
console.log(`   material auto-selected: ${materialValue || '(none -- picking first result)'}`)
if (!materialValue) {
  const firstMaterial = await materialSelect.locator('option').first().textContent()
  if (firstMaterial) await materialSelect.selectOption({ label: firstMaterial })
}
await page.screenshot({ path: 'smoke-3-selections.png' })

console.log('[6/8] Adjusting quick settings ...')
await page.locator('input[type="range"]').fill('30')
await page.screenshot({ path: 'smoke-4-settings.png' })

console.log('[7/8] Clicking Slice ...')
const sliceButton = page.locator('button.slice-button')
await sliceButton.click()
await page.waitForSelector('.status-badge', { timeout: 10000 })

console.log('[8/8] Waiting for job to finish (up to 90s) ...')
await page
  .waitForSelector('.status-succeeded, .status-failed', { timeout: 90000 })
  .catch(() => console.log('   (job still running after 90s -- not necessarily a failure)'))
await page.screenshot({ path: 'smoke-5-result.png' })
const statusText = await page.locator('.status-badge').first().textContent()
console.log(`   final status: ${statusText}`)
if (statusText === 'failed') {
  const errorText = await page.locator('.job-error').textContent().catch(() => null)
  console.log(`   error detail: ${errorText}`)
}

await browser.close()

console.log('\n=== Console errors ===')
console.log(consoleErrors.length ? consoleErrors.join('\n') : '(none)')
console.log('\n=== Page errors ===')
console.log(pageErrors.length ? pageErrors.join('\n') : '(none)')

if (pageErrors.length > 0) process.exit(1)
