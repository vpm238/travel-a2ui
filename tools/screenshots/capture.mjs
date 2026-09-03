#!/usr/bin/env node
/**
 * Captures the screenshots used in the README.
 *
 * It drives the real app against a running `wrangler dev`, in both themes, and
 * exercises the MCP console — which needs no API key, so these are reproducible
 * by anyone with the repo and no credentials at all. That is deliberate: a
 * screenshot nobody else can regenerate is a screenshot that quietly goes stale.
 *
 *   npm run dev:worker            # in another terminal
 *   npm run screenshots
 *
 * The conversation shot (01) comes from `tools/e2e/chat.mjs`, which drives a
 * whole turn against a scripted model — see `npm run screenshots`.
 *
 * Set CHROMIUM_PATH if Playwright's bundled Chromium is somewhere unusual.
 */

import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const OUT = process.argv[2] ?? 'docs/screenshots';
const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8787/';

mkdirSync(OUT, { recursive: true });

const executablePath =
  process.env.CHROMIUM_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';

const browser = await chromium.launch(
  executablePath ? { executablePath } : {},
).catch(() => chromium.launch());

async function open(theme) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 940 },
    colorScheme: theme,
  });
  const page = await context.newPage();
  page.on('pageerror', (error) => console.error('page error:', error.message));
  // A placeholder key gets past the onboarding gate; nothing here calls the API.
  await page.addInitScript(() => {
    localStorage.setItem('travel-a2ui:key', 'sk-ant-screenshot-placeholder');
  });
  await page.goto(BASE, { waitUntil: 'networkidle' });
  return { page, context };
}

for (const theme of ['light', 'dark']) {
  const { page, context } = await open(theme);

  await page.click('button:has-text("MCP")');
  await page.waitForSelector('.mcp__tools button', { timeout: 15000 });
  await page.click('button:has-text("Call show_flight_options")');
  await page.waitForSelector('.tv-flight', { timeout: 20000 });
  await page.screenshot({ path: `${OUT}/02-mcp-${theme}.png` });

  await page.click('.mcp__tools button:has-text("Show a trip dashboard")');
  await page.click('button:has-text("Call show_trip_dashboard")');
  await page.waitForSelector('.tv-stat', { timeout: 20000 });
  await page.screenshot({ path: `${OUT}/03-dashboard-${theme}.png` });

  await page.click('.mcp__tools button:has-text("Show a day-by-day itinerary")');
  await page.click('button:has-text("Call show_itinerary")');
  await page.waitForSelector('.tv-day', { timeout: 20000 });
  await page.screenshot({ path: `${OUT}/04-itinerary-${theme}.png` });

  await page.click('button:has-text("Catalog")');
  await page.waitForSelector('.catalog__list li', { timeout: 20000 });
  await page.screenshot({ path: `${OUT}/05-catalog-${theme}.png` });

  await page.click('button:has-text("Wire")');
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/06-wire-${theme}.png` });

  await context.close();
}

await browser.close();
console.log(`Wrote screenshots to ${OUT}`);
