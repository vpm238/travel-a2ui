#!/usr/bin/env node
/**
 * The agent-framework switch, in a real browser.
 *
 * Two frameworks ship — the Interactions API driven from the Python server,
 * and the Live API relayed through the same server session — and the visible
 * difference is the microphone. This drives the picker and asserts that the
 * microphone follows the choice, and that choosing a framework served by the
 * same origin switches at once rather than waiting for an address.
 *
 * It also asserts the other half of the contract: the frameworks share nothing,
 * so switching reloads and the demo starts over. A stale surface from the
 * previous framework sitting in the new one is the failure that would otherwise
 * reach a viewer.
 *
 * Needs no API key — the picker probes `/api/meta` and nothing here sends a
 * turn — so anyone with the repo can run it.
 *
 *   GEMINI_API_KEY=scripted python3 tools/e2e/scripted_server.py 8130   # another terminal
 *   BASE_URL=http://127.0.0.1:8130/ \
 *   node tools/e2e/frameworks.mjs
 */

import { launchBrowser } from '../browser.mjs';

const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8787/';
let failures = 0;
const check = (label, actual, expected) => {
  const ok = actual === expected;
  if (!ok) failures++;
  console.log(`${ok ? '  ok' : 'FAIL'}  ${label}${ok ? '' : ` — expected ${expected}, got ${actual}`}`);
};

const browser = await launchBrowser();

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

const mics = () => page.locator('.composer__mic').count();
const chosen = async () =>
  (await page.locator('button:has-text("RUNTIME")').first().innerText()).replace(/\s+/g, ' ').trim();

/**
 * Waits for the app to be settled on a framework.
 *
 * Switching reloads, and `canSpeak` comes from `/api/meta`, which is fetched
 * after the page loads — so for a moment after a reload the app is on Live with
 * no microphone yet. Waiting on `networkidle` is not enough: it can resolve
 * against the load that is being navigated away from. Wait for the label, which
 * is only correct once the meta has arrived.
 */
async function settledOn(label) {
  await page
    .locator('button:has-text("RUNTIME")')
    .filter({ hasText: label })
    .first()
    .waitFor({ timeout: 20000 });
  await page.waitForSelector('.composer', { timeout: 20000 });
}

console.log('The framework a traveller chose decides whether there is a microphone.\n');

check('opens on the Interactions runtime', await chosen(), 'RUNTIME Python server ▾');
check('which has no microphone', await mics(), 0);

await page.locator('button:has-text("RUNTIME")').first().click();
await page.waitForSelector('text=Gemini Live', { timeout: 10000 });
await page.locator('button', { hasText: 'Gemini Live' }).first().click();
await settledOn('Gemini Live');

check(
  'switches to Live from the same origin, with no address to type',
  await chosen(),
  'RUNTIME Gemini Live ▾',
);
check('which does have a microphone', await mics(), 1);
check(
  'and says you can still type',
  await page.locator('.composer textarea').getAttribute('placeholder'),
  'Say it, or type it',
);

/*
 * Binding the Live agent, which the traveller should never have to think about.
 *
 * The key here is deliberately fake, so the handshake must fail — and that is
 * the assertion worth having: `ready` is sent only once the Live API accepts
 * the setup, so a bad key never records a receipt for a session that does not
 * exist.
 *
 * The microphone is enabled before the handshake: tapping it binds the agent
 * and then listens, because the setup is the app's problem rather than a
 * button somebody has to find first.
 */
check(
  'the microphone is there to be pressed, setup or no setup',
  await page.locator('.composer__mic').first().isEnabled(),
  true,
);

await page
  .waitForFunction(() => !document.querySelector('.composer__live')?.className.includes('is-instantiating'), {
    timeout: 30000,
  })
  .catch(() => {});

check(
  'refuses a key the Live API rejected, rather than recording one',
  await page.evaluate(() => localStorage.getItem('travel-a2ui:live')),
  null,
);

check(
  'and the choice survived the reload',
  await page.evaluate(() => {
    try {
      return JSON.parse(localStorage.getItem('travel-a2ui:backend') ?? '{}').id;
    } catch {
      return null;
    }
  }),
  'live',
);
check('starting over, with nothing said yet', await page.locator('.turn').count(), 0);
check(
  'and the key kept, because losing that on every switch would be its own annoyance',
  await page.evaluate(() => localStorage.getItem('travel-a2ui:key')),
  'placeholder-for-e2e',
);

// Back again: the microphone has to leave with the framework that owns it.
await page.locator('button:has-text("RUNTIME")').first().click();
await page.waitForSelector('text=Python server', { timeout: 10000 });
await page.locator('button', { hasText: 'Python server' }).first().click();
await settledOn('Python server');

check('switches back', await chosen(), 'RUNTIME Python server ▾');
check('and the microphone goes with it', await mics(), 0);

await browser.close();

console.log(`\n${failures === 0 ? 'All checks passed.' : `${failures} check(s) failed.`}`);
process.exit(failures === 0 ? 0 : 1);
