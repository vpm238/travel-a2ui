#!/usr/bin/env node
/**
 * The README's pictures, taken from the running app.
 *
 * Rewritten, because the version before it could not run at all: it drove a
 * server on port 8787 that no longer exists and clicked a tab that was removed
 * from the app months of decisions ago. Nothing failed loudly — the
 * command simply errored out — so the screenshots in the README quietly stopped
 * being of this product. They were eleven days stale and predated a visual
 * pass, the per-party pricing, the rebuilt stay cards and a header that has
 * since lost two controls.
 *
 * That is the argument for this file existing at all. A screenshot is the only
 * part of a README nobody can diff, so it has to be cheap to retake or it will
 * be wrong.
 *
 * These drive a **real model**, because the pictures are the product: a
 * scripted turn photographs well and shows fixtures nobody chose. It needs a
 * key and it spends a few cents.
 *
 *   uvicorn travel_a2ui.doors.http:app --port 8080 --app-dir apps/server/src
 *   GEMINI_API_KEY=... npm run screenshots
 *
 * Set CHROMIUM_PATH if Playwright's bundled Chromium is somewhere unusual.
 */

import { mkdirSync } from 'node:fs';

import { launchBrowser } from '../browser.mjs';

const OUT = process.argv[2] ?? 'docs/screenshots';
const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8080/';
const KEY = process.env.GEMINI_API_KEY;

if (!KEY) {
  console.error('GEMINI_API_KEY is required — these drive the real agent.');
  process.exit(2);
}

mkdirSync(OUT, { recursive: true });

/** What the traveller says, in the order a visitor would say it. */
const ASK = 'Six days in Madrid in April 2027, two of us, flying from JFK. Show me flights.';

const browser = await launchBrowser();

async function open(theme) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 940 },
    colorScheme: theme,
    deviceScaleFactor: 2, // Retina, so the README is not a blurry png.
  });
  const page = await context.newPage();
  page.on('pageerror', (error) => console.error('page error:', error.message));
  await page.addInitScript(([key]) => localStorage.setItem('travel-a2ui:key', key), [KEY]);
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForSelector('.composer', { timeout: 30000 });
  return { page, context };
}

/** One real turn, and the surface it drew.
 *
 * Retried once, because a turn is a real model call and a busy minute should
 * not cost the whole run — the first version lost four captured images to one
 * timeout on the fifth.
 */
async function converse(page, attempt = 1) {
  const composer = page.locator('.composer textarea');
  await composer.fill(ASK);
  await composer.press('Enter');
  try {
    await page.locator('.turn__surface').first().waitFor({ state: 'attached', timeout: 120000 });
  } catch (error) {
    if (attempt >= 2) throw error;
    console.warn('  (no surface in time — asking once more)');
    return converse(page, attempt + 1);
  }
  // The panel is a second model call and lands after the answer; waiting for it
  // is the difference between photographing the product and photographing a
  // half-painted one.
  await page
    .waitForFunction(
      () => (document.querySelector('.sidebar')?.textContent ?? '').includes('Change'),
      { timeout: 60000 },
    )
    .catch(() => console.warn('  (the panel had no Change buttons in time)'));
  await page.waitForTimeout(1200);
}

const THEMES = (process.env.THEMES ?? 'light,dark').split(',');

for (const theme of THEMES) {
  console.log(`\n=== ${theme} ===`);
  const { page, context } = await open(theme);

  console.log('  a real turn…');
  await converse(page);
  await page.screenshot({ path: `${OUT}/01-chat-${theme}.png` });
  console.log(`  01-chat-${theme}.png`);

  // The panel on its own, which is the shot that shows what "the record" means.
  const panel = page.locator('.sidebar');
  if (await panel.count()) {
    await panel.first().screenshot({ path: `${OUT}/02-panel-${theme}.png` });
    console.log(`  02-panel-${theme}.png`);
  }

  await page.click('button:has-text("Home")');
  await page
    .waitForSelector('.tv-stat, .home', { timeout: 90000 })
    .catch(() => console.warn('  (home did not draw)'));
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${OUT}/03-home-${theme}.png` });
  console.log(`  03-home-${theme}.png`);

  await page.click('button:has-text("Catalog")');
  await page.waitForSelector('.catalog__grid li', { timeout: 30000 });
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/04-catalog-${theme}.png` });
  console.log(`  04-catalog-${theme}.png`);

  await page.click('button:has-text("Wire")');
  await page.waitForTimeout(900);
  await page.screenshot({ path: `${OUT}/05-wire-${theme}.png` });
  console.log(`  05-wire-${theme}.png`);

  await context.close();
}

await browser.close();
console.log(`\nWrote screenshots to ${OUT}`);
