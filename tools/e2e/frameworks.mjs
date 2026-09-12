#!/usr/bin/env node
/**
 * The agent-framework switch, in a real browser.
 *
 * Two frameworks ship — the Interactions API driven from this Worker, and the
 * Live API relayed through the session Durable Object — and the visible
 * difference is the microphone. This drives the picker and asserts that the
 * microphone follows the choice.
 *
 * It exists because the bug it catches was invisible to every unit test. The
 * picker decided which frameworks needed an address with `id !== 'worker'`,
 * written when the only second runtime was a managed agent somewhere else. Live
 * is served by this same Worker, so choosing it set a draft and waited forever
 * for a URL it does not have: the entry highlighted, the picker stayed open,
 * and nothing switched. Everything typechecked. Every test passed.
 *
 * Needs no API key — the picker probes `/api/meta` and nothing here sends a
 * turn — so anyone with the repo can run it.
 *
 *   npm run dev:worker            # in another terminal
 *   node tools/e2e/frameworks.mjs
 */

import { chromium } from 'playwright';

const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8787/';
const executablePath =
  process.env.CHROMIUM_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';

let failures = 0;
const check = (label, actual, expected) => {
  const ok = actual === expected;
  if (!ok) failures++;
  console.log(`${ok ? '  ok' : 'FAIL'}  ${label}${ok ? '' : ` — expected ${expected}, got ${actual}`}`);
};

const browser = await chromium
  .launch({ executablePath })
  .catch(() => chromium.launch());

const context = await browser.newContext({ viewport: { width: 1280, height: 820 } });
const page = await context.newPage();
page.on('pageerror', (error) => {
  console.error('page error:', error.message);
  failures++;
});

// Gets past the onboarding gate. Nothing here calls the model.
await page.addInitScript(() => {
  localStorage.setItem('travel-a2ui:key', 'placeholder-for-e2e');
});

await page.goto(BASE, { waitUntil: 'networkidle' });
await page.waitForSelector('.composer', { timeout: 20000 });

const mics = () => page.locator('.composer__call').count();
const chosen = async () =>
  (await page.locator('button:has-text("RUNTIME")').first().innerText())
    .replace(/\s+/g, ' ')
    .trim();

console.log('The framework a traveller chose decides whether there is a microphone.\n');

check('opens on the Interactions runtime', await chosen(), 'RUNTIME Cloudflare Worker ▾');
check('which has no microphone', await mics(), 0);

await page.locator('button:has-text("RUNTIME")').first().click();
await page.waitForSelector('text=Gemini Live', { timeout: 10000 });
await page.locator('button', { hasText: 'Gemini Live' }).first().click();
await page.waitForTimeout(1500);

check('switches to Live from the same origin, with no address to type', await chosen(), 'RUNTIME Gemini Live ▾');
check('which does have a microphone', await mics(), 1);
check(
  'and says you can still type',
  await page.locator('.composer textarea').getAttribute('placeholder'),
  'Say it, or type it',
);

// Back again: the microphone has to leave with the framework that owns it.
await page.locator('button:has-text("RUNTIME")').first().click();
await page.waitForTimeout(300);
await page.locator('button', { hasText: 'Cloudflare Worker' }).first().click();
await page.waitForTimeout(1500);

check('switches back', await chosen(), 'RUNTIME Cloudflare Worker ▾');
check('and the microphone goes with it', await mics(), 0);

await browser.close();

console.log(`\n${failures === 0 ? 'All checks passed.' : `${failures} check(s) failed.`}`);
process.exit(failures === 0 ? 0 : 1);
