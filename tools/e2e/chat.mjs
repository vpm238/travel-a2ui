#!/usr/bin/env node
/**
 * End-to-end check of the inline modality, with a scripted model.
 *
 * The unit tests cover the compiler, the store and the agent loop; the MCP
 * console proves the renderer. What none of them touch is the path a person
 * actually takes: type a message, watch a surface appear under the reply, click
 * something in it, and have that click become the next turn.
 *
 * So this drives the real app in a real browser and intercepts `/api/chat`,
 * replaying a canned turn. The stub runs the *real* `ExpressStreamParser` and
 * compiler over a scripted model output — the same code the Worker runs — so
 * what reaches the browser is exactly the event sequence a live turn produces,
 * including the partial `ui` events from a block split mid-constructor. No API
 * key, no model, no cost, and it fails loudly when the wiring rots.
 *
 *   npm run dev:worker      # in another terminal
 *   node tools/e2e/chat.mjs [--screenshot docs/screenshots/01-chat-light.png]
 */

import { chromium } from 'playwright';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { ExpressCompiler, ExpressStreamParser } from '../../packages/express/dist/index.js';

const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8787/';
/**
 * Which Chromium to drive.
 *
 * CHROMIUM_PATH wins; otherwise a preinstalled browser is used if one is
 * actually on disk, and failing that Playwright resolves its own — which is the
 * case on a CI runner after `playwright install`. Naming a path that does not
 * exist fails with "executable doesn't exist", which says nothing about why.
 */
const PREINSTALLED = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const executablePath =
  process.env.CHROMIUM_PATH || (existsSync(PREINSTALLED) ? PREINSTALLED : undefined);
const launchBrowser = (options = {}) =>
  chromium.launch({ ...(executablePath ? { executablePath } : {}), ...options });

const shotIndex = process.argv.indexOf('--screenshot');
const SHOT = shotIndex === -1 ? null : process.argv[shotIndex + 1];

/** The turn the fake model produces, in the order a real one would stream it. */
const FIRST_TURN = [
  { type: 'start', model: 'claude-opus-5', skill: 'express-monolithic', surfaceId: 'inline-1' },
  { type: 'tool', name: 'search_flights', input: { destination: 'Madrid' }, status: 'running' },
  { type: 'tool_result', name: 'search_flights', result: { count: 3 }, isError: false },
];

const EXPRESS = `surface("inline-1")
$/trip/selectedOutbound = ""
heading = Text("Outbound · JFK → MAD · Sun 12 Apr", variant="h3")
f1 = FlightOption("Iberia", "18:40", "08:15 +1", "JFK", "MAD", "$412", Event("select_flight", {id: "IB6250", price: "$412"}), duration="7h 35m", stops="Nonstop", flightNumber="IB6250", badge="Cheapest")
f2 = FlightOption("Delta", "21:10", "10:50 +1", "JFK", "MAD", "$468", Event("select_flight", {id: "DL126", price: "$468"}), duration="7h 40m", stops="Nonstop", flightNumber="DL126")
f3 = FlightOption("TAP", "17:25", "11:05 +1", "JFK", "MAD", "$367", Event("select_flight", {id: "TP208", price: "$367"}), duration="11h 40m", stops="1 stop · LIS", flightNumber="TP208", badge="Lowest fare")
note = Text("Prices are per traveller, round trip.", variant="caption")
root = Column([heading, f1, f2, f3, note])`;

const SECOND_TURN = [
  { type: 'start', model: 'claude-opus-5', skill: 'express-monolithic', surfaceId: 'inline-2' },
  { type: 'tool', name: 'save_trip', input: { selectedFlight: 'IB6250' }, status: 'running' },
  { type: 'tool_result', name: 'save_trip', result: { saved: true }, isError: false },
  { type: 'trip', trip: { destination: 'Madrid', selectedFlight: 'IB6250', travelers: 2 } },
  { type: 'text', delta: 'Held the Iberia fare. Where do you want to stay?' },
  { type: 'done', stopReason: 'end_turn' },
];

const failures = [];
const check = (label, ok) => {
  console.log(`${ok ? '  ok  ' : ' FAIL '} ${label}`);
  if (!ok) failures.push(label);
};

const here = dirname(fileURLToPath(import.meta.url));
const catalog = JSON.parse(
  readFileSync(join(here, '..', '..', 'catalogs', 'a2ui-travel', 'catalog.json'), 'utf8'),
);
const compiler = new ExpressCompiler(catalog, 'v0.9.1');

function toSse(events) {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('');
}

/**
 * Runs the model's raw output through the same splitter the Worker uses.
 *
 * The chunk boundaries matter: the block is cut mid-constructor, so the parser
 * has to tolerate a truncated tail and the browser has to survive a partial
 * surface followed by a complete one.
 */
function turnEvents(surfaceId, prose, express, tail) {
  const stream = new ExpressStreamParser(compiler, {
    surfaceId,
    catalogId: catalog.catalogId,
    version: 'v0.9.1',
  });
  const chunks = [
    prose,
    `<a2ui>\n${express.slice(0, 320)}`,
    `${express.slice(320)}\n</a2ui>\n`,
    tail,
  ];

  const events = [];
  for (const chunk of chunks) {
    for (const event of stream.push(chunk)) {
      if (event.type === 'text') events.push({ type: 'text', delta: event.delta });
      else if (event.type === 'ui') {
        events.push({ type: 'ui', surfaceId, messages: event.messages, done: event.done });
      }
    }
  }
  for (const event of stream.end()) {
    if (event.type === 'text') events.push({ type: 'text', delta: event.delta });
    else if (event.type === 'ui') {
      events.push({ type: 'ui', surfaceId, messages: event.messages, done: event.done });
    }
  }
  return events;
}

const browser = await launchBrowser();
const context = await browser.newContext({ viewport: { width: 1440, height: 940 } });
const page = await context.newPage();

page.on('pageerror', (error) => check(`no page exception (${error.message})`, false));

await page.addInitScript(() => {
  localStorage.setItem('travel-a2ui:key', 'sk-ant-e2e-placeholder');
  localStorage.setItem('travel-a2ui:session', 'e2e-session');
});

/** Every `/api/chat` body the app sent, so we can assert on the second one. */
const sent = [];
let turn = 0;

await page.route('**/api/chat', async (route) => {
  sent.push(JSON.parse(route.request().postData() ?? '{}'));
  const index = turn++;

  const body =
    index === 0
      ? toSse([
          ...FIRST_TURN,
          ...turnEvents(
            'inline-1',
            'Three nonstops on the 12th. The Iberia one lands early enough to still get dinner.\n\n',
            EXPRESS,
            '\nWant me to hold one?',
          ),
          { type: 'usage', inputTokens: 4210, outputTokens: 380, cacheReadTokens: 3900, cacheWriteTokens: 0 },
          { type: 'done', stopReason: 'end_turn' },
        ])
      : toSse(SECOND_TURN);

  await route.fulfill({
    status: 200,
    headers: { 'content-type': 'text/event-stream; charset=utf-8', 'cache-control': 'no-store' },
    body,
  });
});

console.log(`Driving ${BASE}\n`);
await page.goto(BASE, { waitUntil: 'networkidle' });

// --- turn one: type, send, watch a surface appear -------------------------
await page.waitForSelector('.chat__intro', { timeout: 15000 });
await page.fill('.composer textarea', 'Six days in Madrid in April, two of us');
await page.click('.composer__send');

await page.waitForSelector('.tv-flight', { timeout: 15000 });
check('an inline surface renders under the reply', true);

const flights = await page.locator('.tv-flight').count();
check(`all three flight options render (${flights})`, flights === 3);

const badge = await page.locator('.tv-badge').first().textContent();
check(`badges render (${badge?.trim()})`, Boolean(badge?.trim()));

const prose = (await page.locator('.bubble--agent').first().textContent()) ?? '';
check('prose stays prose', prose.includes('Three nonstops'));
check('Express never leaks into the prose', !prose.includes('FlightOption'));

const tools = await page.locator('.turn__tools li').count();
check(`tool activity is shown (${tools})`, tools === 1);

// --- turn two: click a flight, and the click becomes the next turn --------
await page.locator('.tv-flight').first().click();
await page.waitForFunction(() => document.querySelectorAll('.bubble--event').length > 0, {
  timeout: 15000,
});

// Find the turn the click produced rather than assuming an index: the sidebar
// rebuilds itself on its own schedule and may get there first.
const fromClick = sent.find((body) => body.message?.includes('select_flight'));
check('clicking a flight sends another turn', Boolean(fromClick));
check(
  `the event name reaches the model (${fromClick?.message?.slice(0, 40)}…)`,
  Boolean(fromClick?.message?.includes('select_flight')),
);
check('the chosen flight id travels with it', Boolean(fromClick?.message?.includes('IB6250')));
check(
  'the surface data model is attached',
  Boolean(fromClick?.surfaceState && 'trip' in fromClick.surfaceState),
);

await page.waitForSelector('.sidebar__trip', { timeout: 15000 });
const decided = (await page.locator('.sidebar__trip').textContent()) ?? '';
check('trip state reaches the sidebar', decided.includes('IB6250'));

const status = (await page.locator('.statusbar').textContent()) ?? '';
check('token usage is reported', /cached/.test(status));

// --- the wire inspector sees the same surface ----------------------------
await page.click('button:has-text("Wire")');
await page.waitForSelector('.protocol__tabs button', { timeout: 15000 });

// Pick the surface deliberately. Which one the pane opens on depends on what
// else exists — the panel rebuilds itself when the trip changes shape, so
// relying on the default made this test fail for a reason that had nothing to
// do with the wire view.
await page.locator('.protocol__tabs button', { hasText: 'inline-1' }).click();

// The catalog is fetched to decompile, so the pane starts as a placeholder.
await page.waitForSelector('.protocol__pane .code', { timeout: 15000 });
const express = (await page.locator('.protocol__pane').first().textContent()) ?? '';
check('the wire view recovers the Express', express.includes('FlightOption('));
check('and reports the size difference', /% smaller/.test(express));

if (SHOT) {
  await page.click('button:has-text("Chat")');
  await page.waitForSelector('.tv-flight', { timeout: 15000 });
  mkdirSync(dirname(SHOT), { recursive: true });
  await page.screenshot({ path: SHOT });
  console.log(`\nScreenshot: ${SHOT}`);
}

await browser.close();

console.log(`\n${failures.length === 0 ? 'All checks passed.' : `${failures.length} failed.`}`);
process.exit(failures.length === 0 ? 0 : 1);
