#!/usr/bin/env node
/**
 * A spoken turn, drawn — in a real browser, against a real model.
 *
 * This is the test that would have caught the bug the whole Live feature had.
 * The relay was fine: driven directly over a WebSocket it answered speech with
 * speech, called `save_trip` and `show_flight_options`, and sent A2UI down. The
 * browser never sent a byte, because both `AudioContext`s were constructed
 * after `await getUserMedia` — the user gesture is spent by then, so Chrome's
 * autoplay policy starts them *suspended*, a suspended capture context never
 * fires `audioprocess`, and nothing throws anywhere.
 *
 * So nothing short of a real browser could see it, and a real browser needs a
 * microphone. Chromium's fake device supplies one, which also grants the
 * permission prompt — the point is not what the fake microphone says (it is a
 * beep), it is that opening it leaves the contexts *running*. The turn itself
 * goes over the Live session's own text channel, which is what the composer
 * does when somebody types mid-conversation.
 *
 * Asserts, in order: the contexts are running rather than suspended; the Live
 * session reaches `ready`; a spoken-channel turn draws a surface into the
 * transcript; and that surface contains real components rather than an empty
 * frame.
 *
 * Needs a key and spends tokens, so it is not in `npm run e2e`.
 *
 *   GEMINI_API_KEY=... node tools/e2e/live.mjs
 *   GEMINI_API_KEY=... BASE_URL=https://…run.app/ node tools/e2e/live.mjs
 */

import { launchBrowser } from '../browser.mjs';

const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8080/';
const KEY = process.env.GEMINI_API_KEY;
if (!KEY) {
  console.error('GEMINI_API_KEY is required — this one drives a real model.');
  process.exit(2);
}

let failures = 0;
const check = (label, actual, expected) => {
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`${ok ? '  ok' : 'FAIL'}  ${label}${ok ? '' : ` — expected ${expected}, got ${actual}`}`);
};
const ok = (label, condition, detail = '') => {
  if (!condition) failures += 1;
  console.log(`${condition ? '  ok' : 'FAIL'}  ${label}${condition ? '' : ` — ${detail}`}`);
};

const browser = await launchBrowser({
  args: [
    // A microphone that needs no hardware and no prompt. Without the second
    // flag `getUserMedia` hangs on a permission dialog nobody can click.
    '--use-fake-device-for-media-stream',
    '--use-fake-ui-for-media-stream',
    '--autoplay-policy=user-gesture-required',
  ],
});

const context = await browser.newContext({
  viewport: { width: 1280, height: 900 },
  permissions: ['microphone'],
});
const page = await context.newPage();

const pageErrors = [];
page.on('pageerror', (error) => pageErrors.push(error.message));

// Signed in, and on the Live framework before the first paint.
await page.addInitScript(
  ([key]) => {
    localStorage.setItem('travel-a2ui:key', key);
    localStorage.setItem(
      'travel-a2ui:backend',
      JSON.stringify({ id: 'live', origin: window.location.origin }),
    );
    // Every AudioContext this page makes, remembered — so the assertion is
    // about the real objects the app built, not a reimplementation of them.
    // Every frame the relay sends down, recorded before the app sees it — so
    // "the server never sent a surface" and "the client dropped one" are
    // different answers rather than the same silence.
    window.__frames = [];
    const NativeSocket = window.WebSocket;
    window.WebSocket = class extends NativeSocket {
      constructor(...args) {
        super(...args);
        this.addEventListener('message', (event) => {
          try {
            const frame = JSON.parse(String(event.data));
            window.__frames.push(
              frame.type === 'audio' ? { type: 'audio' } : frame,
            );
          } catch {
            window.__frames.push({ type: 'unparseable' });
          }
        });
        this.addEventListener('close', (event) =>
          window.__frames.push({ type: '__close__', code: event.code, reason: event.reason }),
        );
        this.addEventListener('error', () => window.__frames.push({ type: '__socketerror__' }));
      }
    };

    const Native = window.AudioContext;
    window.__contexts = [];
    window.AudioContext = class extends Native {
      constructor(...args) {
        super(...args);
        window.__contexts.push(this);
      }
    };
  },
  [KEY],
);

await page.goto(BASE, { waitUntil: 'networkidle' });
await page.waitForSelector('.composer', { timeout: 30000 });

const mic = page.locator('.composer__mic');
check('the Live framework puts a microphone in the composer', await mic.count(), 1);

console.log('\n--- tapping the microphone ---');
await mic.click();

// The tap opens the microphone and instantiates the session behind it.
await page
  .waitForFunction(() => (window.__contexts ?? []).length >= 2, { timeout: 30000 })
  .catch(() => {});

const states = await page.evaluate(() => (window.__contexts ?? []).map((c) => c.state));
console.log(`  audio contexts: ${JSON.stringify(states)}`);
ok(
  'both audio contexts are running, not suspended',
  states.length >= 2 && states.every((state) => state === 'running'),
  `got ${JSON.stringify(states)} — a suspended capture context never sends a byte`,
);

// Typing while listening goes *into* the Live session rather than starting a
// second conversation beside it, which is the path a spoken turn shares.
console.log('\n--- sending a turn over the Live session ---');
const SETTLE = Number(process.env.SETTLE_MS ?? 0);
if (SETTLE) await page.waitForTimeout(SETTLE);
const composer = page.locator('.composer textarea');
await composer.fill(
  'Find me flights from JFK to Madrid on the 12th of April 2027 for two people. Put them on screen.',
);
await composer.press('Enter');

const surface = page.locator('.turn__surface');
let drew = true;
await surface
  .first()
  .waitFor({ state: 'attached', timeout: 60000 })
  .catch(() => {
    drew = false;
  });
ok('a spoken turn draws a surface into the transcript', drew, 'no .turn__surface appeared');

const frames = await page.evaluate(() => window.__frames ?? []);
const counts = {};
for (const frame of frames) counts[frame.type] = (counts[frame.type] ?? 0) + 1;
console.log(`  frames down: ${JSON.stringify(counts)}`);
for (const frame of frames) {
  if (['error', '__close__', '__socketerror__', 'tool', 'transcript'].includes(frame.type)) {
    console.log(`    ${JSON.stringify(frame).slice(0, 220)}`);
  }
}

if (drew) {
  const components = await page.evaluate(() => {
    const node = document.querySelector('.turn__surface');
    return {
      children: node ? node.querySelectorAll('*').length : 0,
      text: (node?.textContent ?? '').slice(0, 160),
    };
  });
  console.log(`  surface: ${components.children} nodes — ${JSON.stringify(components.text)}`);
  ok(
    'the surface has real components in it, not an empty frame',
    components.children > 5,
    `only ${components.children} nodes`,
  );
}

if (pageErrors.length) {
  failures += pageErrors.length;
  console.log(`\nFAIL  ${pageErrors.length} page error(s):`);
  for (const error of pageErrors) console.log(`        ${error}`);
}

await browser.close();
console.log(`\n${failures ? `${failures} failure(s)` : 'all checks passed'}`);
process.exit(failures ? 1 : 0);
