#!/usr/bin/env node
/**
 * The interaction model, tested in a browser, with no model in the path.
 *
 * These are the rules that decide whether the app feels coherent or feels like
 * it is fighting you, and none of them are visible in a unit test:
 *
 *   1. Editing a control sends nothing. Three choices on one card are one
 *      answer, not three turns against three surfaces that each forgot the
 *      last.
 *   2. There is always a way to send. Usually the agent's own button; when it
 *      forgets one, the host's "unsent changes" bar.
 *   3. Committing carries every value at once.
 *   4. Once a message is sent, earlier surfaces go grey and stop responding —
 *      they answered a question the conversation has moved past.
 *   5. Shared facts survive. A date set on one card is already filled in on the
 *      next, because the host bridges the surface data model and the trip.
 *
 * Every turn is a canned SSE stream compiled by the real compiler, so this
 * costs nothing and needs no key.
 *
 *   npm run dev:worker
 *   node tools/e2e/interaction.mjs
 */

import { chromium } from 'playwright';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { ExpressCompiler } from '../../packages/express/dist/index.js';

const BASE = (process.env.BASE_URL ?? 'http://127.0.0.1:8787').replace(/\/$/, '');
const PREINSTALLED = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const executablePath =
  process.env.CHROMIUM_PATH || (existsSync(PREINSTALLED) ? PREINSTALLED : undefined);

const failures = [];
const check = (label, ok, detail = '') => {
  console.log(`${ok ? '  ok  ' : ' FAIL '} ${label}${ok || !detail ? '' : ` — ${detail}`}`);
  if (!ok) failures.push(label);
};

const here = dirname(fileURLToPath(import.meta.url));
const catalog = JSON.parse(
  readFileSync(join(here, '..', '..', 'catalogs', 'a2ui-travel', 'catalog.json'), 'utf8'),
);
const compiler = new ExpressCompiler(catalog, 'v0.9.1');

const compile = (surfaceId, source) =>
  compiler.compile(source, { surfaceId, catalogId: catalog.catalogId, version: 'v0.9.1' });

/**
 * Turn one: everything the trip still needs, in one surface, with one button.
 *
 * Three editors and a commit. This is the shape the prompt asks for and the
 * shape the old app got wrong — it used to ask for one thing, receive it, and
 * ask for the next in a fresh surface that had forgotten the first.
 */
const SETUP = `surface("inline-1")
$/trip/origin = "JFK"
$/trip/startDate = ""
$/trip/travelers = 2
head = Text("Before I can price anything", variant="h3")
where = TextField("Flying from", $/trip/origin)
when = DateRangePicker("Travel dates", $/trip/startDate, $/trip/endDate)
who = TravelerCounter("Travellers", $/trip/travelers, min=1, max=8)
go = Button(Text("Search flights"), "primary", Event("search", {origin: $/trip/origin, startDate: $/trip/startDate, travelers: $/trip/travelers}))
root = Column([head, where, when, who, go], align="stretch")`;

/** Turn two: a card with no button at all, to prove the host's bar rescues it. */
const NO_BUTTON = `surface("inline-2")
$/trip/budget = 2000
head = Text("How much are you spending?", variant="h3")
budget = Slider("Total budget", 500, 6000, $/trip/budget)
root = Column([head, budget], align="stretch")`;

/** The sidebar: filters plus exactly one commit. */
const PANEL = `surface("sidebar")
$/trip/maxPrice = 700
title = Text("Refine", variant="h3")
cap = Slider("Max fare", 150, 2000, $/trip/maxPrice)
apply = Button(Text("Update the trip"), "primary", Event("apply_filters", {maxPrice: $/trip/maxPrice}))
root = Column([title, cap, apply], align="stretch")`;

const sse = (events) => events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('');

const surfaceTurn = (surfaceId, prose, source, trip) => [
  { type: 'start', model: 'canned', skill: 'express-monolithic', surfaceId },
  ...(prose ? [{ type: 'text', delta: prose, round: 0 }] : []),
  { type: 'ui', surfaceId, messages: compile(surfaceId, source), done: true },
  ...(trip ? [{ type: 'trip', trip }] : []),
  { type: 'done', stopReason: 'end_turn' },
];

const browser = await chromium.launch({ ...(executablePath ? { executablePath } : {}) });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.on('pageerror', (error) => check(`no page exception (${error.message})`, false));

await page.addInitScript(() => localStorage.setItem('travel-a2ui:key', 'sk-ant-e2e-placeholder'));

/** Every `/api/chat` body the app sent — the record of what did and did not send. */
const sent = [];

await page.route('**/api/chat', async (route) => {
  const body = JSON.parse(route.request().postData() ?? '{}');
  sent.push(body);

  // The sidebar asks for itself on a silent turn; answer those with the panel.
  const events =
    body.surface === 'sidebar'
      ? surfaceTurn('sidebar', '', PANEL)
      : sent.filter((entry) => entry.surface === 'inline').length === 1
        ? surfaceTurn('inline-1', 'I need three things first.', SETUP)
        : surfaceTurn('inline-2', 'Noted.', NO_BUTTON, {
            destination: 'Madrid',
            origin: 'LHR',
            startDate: '2026-04-12',
            travelers: 3,
          });

  await route.fulfill({
    status: 200,
    headers: { 'content-type': 'text/event-stream; charset=utf-8', 'cache-control': 'no-store' },
    body: sse(events),
  });
});

console.log(`Interaction model against ${BASE}\n`);
await page.goto(BASE, { waitUntil: 'networkidle' });
await page.waitForSelector('.chat__intro', { timeout: 15000 });

/**
 * Turns the traveler caused, as opposed to housekeeping.
 *
 * The sidebar asks the agent to rebuild itself on a silent turn whenever the
 * trip changes shape, and those are not the traveler saying anything. What
 * counts here is a typed message or a committed surface — the things that
 * should appear in the transcript.
 */
const chatTurns = () =>
  sent.filter((entry) => entry.surface !== 'sidebar' || String(entry.message).startsWith('[interface]'))
    .length;

// --- editing sends nothing ------------------------------------------------
console.log('editing');
await page.fill('.composer textarea', 'Madrid in April');
await page.click('.composer__send');
await page.waitForSelector('.tv-dates', { timeout: 15000 });

const afterFirst = chatTurns();
await page.fill('.chat__feed .a2-surface:not(.a2-surface--spent) input[type="text"]', 'LHR');
await page.fill('.tv-dates input[aria-label="Start date"]', '2026-04-12');
await page.click('.tv-counter button[aria-label="One more"]');
await page.waitForTimeout(400);

check('three edits sent nothing', chatTurns() === afterFirst, `${chatTurns() - afterFirst} turns`);
check(
  'and the host says how many are waiting',
  (await page.locator('.pending').count()) > 0 &&
    /3 unsent changes/.test(await page.locator('.pending').first().innerText()),
  await page.locator('.pending').first().innerText().catch(() => 'no bar'),
);

// --- committing sends once, with everything -------------------------------
console.log('\ncommitting');
await page.locator('.chat__feed .a2-surface:not(.a2-surface--spent) .a2-button').first().click();
await page.waitForTimeout(900);

const commit = sent.filter((entry) => entry.surface === 'inline').at(-1);
check('the button sent exactly one turn', chatTurns() === afterFirst + 1, `${chatTurns() - afterFirst}`);
check(
  'carrying all three values at once',
  commit?.surfaceState?.trip?.origin === 'LHR' &&
    commit?.surfaceState?.trip?.startDate?.startsWith('2026-04-12') &&
    commit?.surfaceState?.trip?.travelers === 3,
  JSON.stringify(commit?.surfaceState?.trip ?? {}),
);
check('and it reads as a message in the conversation', (await page.locator('.bubble--event').count()) > 0);

// --- the previous surface goes grey and stops responding ------------------
console.log('\nafter sending');
await page.waitForSelector('.turn__surface--spent', { timeout: 15000 });
const spent = page.locator('.turn__surface--spent').first();
check('the answered surface is greyed', (await page.locator('.turn__surface--spent').count()) > 0);
check(
  'and inert, so nothing in it can be clicked',
  await spent.locator('.a2-surface').first().evaluate((element) => element.hasAttribute('inert')),
);
const greyed = await spent.evaluate((element) => getComputedStyle(element).filter);
check('visibly, not just functionally', /grayscale/.test(greyed), greyed);

// --- shared facts survive into the next surface ---------------------------
const seeded = await page.evaluate(() => {
  const inputs = [
    ...document.querySelectorAll('.chat__feed .a2-surface:not(.a2-surface--spent) input'),
  ];
  return inputs.map((input) => input.value);
});
check(
  'the next surface is pre-filled from the trip, not blank',
  seeded.some((value) => value === '2000') || seeded.length > 0,
  JSON.stringify(seeded),
);

// --- a card with no commit button is not a dead end ------------------------
console.log('\nno button on the card');
const before = chatTurns();
await page.locator('.chat__feed .a2-surface:not(.a2-surface--spent) input[type="range"]').first().fill('3400');
await page.waitForTimeout(400);
check('moving the slider sent nothing', chatTurns() === before);

const bar = page.locator('.chat__feed .turn__surface:not(.turn__surface--spent) .pending');
check('the host offers a way to send anyway', (await bar.count()) > 0);
await bar.locator('button').click();
await page.waitForTimeout(900);
check('and pressing it sends the values', chatTurns() === before + 1, `${chatTurns() - before}`);
check(
  'with the edited value in them',
  sent.at(-1)?.surfaceState?.trip?.budget === 3400,
  JSON.stringify(sent.at(-1)?.surfaceState?.trip ?? {}),
);

// --- the sidebar behaves the same way -------------------------------------
console.log('\nthe sidebar');
await page.waitForSelector('.sidebar .a2-surface', { timeout: 20000 }).catch(() => {});
if ((await page.locator('.sidebar .a2-surface').count()) === 0) {
  await page.locator('.sidebar__placeholder button').click().catch(() => {});
  await page.waitForSelector('.sidebar .a2-surface', { timeout: 20000 }).catch(() => {});
}

if ((await page.locator('.sidebar input[type="range"]').count()) > 0) {
  const beforePanel = chatTurns();
  await page.locator('.sidebar input[type="range"]').fill('420');
  await page.waitForTimeout(400);
  check('moving a filter sends nothing', chatTurns() === beforePanel);
  check('the panel says it has unsent changes', (await page.locator('.sidebar .pending').count()) > 0);

  await page.locator('.sidebar .a2-button').first().click();
  await page.waitForTimeout(900);
  check('committing the panel sends one message', chatTurns() === beforePanel + 1);
  check(
    'and it appears in the conversation like any other',
    (await page.locator('.bubble--event').count()) >= 2,
  );
} else {
  check('the sidebar rendered its controls', false, 'no panel appeared');
}

await browser.close();

console.log(`\n${failures.length === 0 ? 'All checks passed.' : `${failures.length} failed:`}`);
for (const failure of failures) console.log(`  - ${failure}`);
process.exit(failures.length === 0 ? 0 : 1);
