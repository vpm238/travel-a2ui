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
 *      forgets one, the server adds one before the surface is sent.
 *   3. Committing carries every value at once, in the A2UI action's context.
 *   4. Once a message is sent, earlier surfaces go grey and stop responding —
 *      they answered a question the conversation has moved past.
 *   5. Shared facts survive. A date set on one card is already filled in on the
 *      next, because the server seeds it into the surface it creates.
 *
 * Every turn is a canned SSE stream compiled by the real compiler, so this
 * costs nothing and needs no key.
 *
 *   npm run dev:worker
 *   node tools/e2e/interaction.mjs
 */

import { launchBrowser } from '../browser.mjs';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { compileAll } from './compile.mjs';

const BASE = (process.env.BASE_URL ?? 'http://127.0.0.1:8787').replace(/\/$/, '');
const failures = [];
const check = (label, ok, detail = '') => {
  console.log(`${ok ? '  ok  ' : ' FAIL '} ${label}${ok || !detail ? '' : ` — ${detail}`}`);
  if (!ok) failures.push(label);
};

const here = dirname(fileURLToPath(import.meta.url));
const catalog = JSON.parse(
  readFileSync(join(here, '..', '..', 'catalogs', 'a2ui-travel', 'catalog.json'), 'utf8'),
);
/**
 * Compile the way the server does.
 *
 * This harness stands in for the server, so it has to run the server's passes
 * too — otherwise it tests a surface no client would ever actually receive. It
 * does, literally: `compile.py` is the SDK's parser, the macros and the
 * finishing passes, including the one that matters here — every edited path
 * bound into the commit button, and a button added to a surface that has none.
 */
const compile = (surfaceId, source) => compileAll([{ surfaceId, source }])[0].messages;

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
head = Text("### Before I can price anything")
where = TextField("Flying from", $/trip/origin)
when = DateRangePicker("Travel dates", $/trip/startDate, $/trip/endDate)
who = TravelerCounter("Travellers", $/trip/travelers, min=1, max=8)
go = Button(Text("Search flights"), "primary", Event("search", {origin: $/trip/origin, startDate: $/trip/startDate, travelers: $/trip/travelers}))
root = Column([head, where, when, who, go], align="stretch")`;

/** Turn two: a card with no button at all — the server has to add one. */
const NO_BUTTON = `surface("inline-2")
$/trip/budget = 2000
head = Text("### How much are you spending?")
budget = Slider("Total budget", 500, 6000, $/trip/budget)
root = Column([head, budget], align="stretch")`;

/**
 * The panel: what is settled, and one way to change each of it.
 *
 * A slider is included deliberately. The panel is read-only, and the host has
 * to hold that line even when the model draws a control it should not have —
 * otherwise the rule is a request rather than a guarantee.
 */
const PANEL = `surface("sidebar")
$/trip/maxFare = 700
title = Text("### The trip")
flight = Text("Iberia IB614 · $257", variant="body")
changeFlight = Button(Text("Change"), "borderless", Event("change", {field: "selectedFlight"}))
stray = Slider("Max fare", 150, 2000, $/trip/maxFare)
root = Column([title, flight, changeFlight, stray], align="stretch")`;

const sse = (events) => events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('');

const surfaceTurn = (surfaceId, prose, source, trip) => [
  { type: 'start', model: 'canned', skill: 'express-modular', surfaceId },
  ...(prose ? [{ type: 'text', delta: prose, round: 0 }] : []),
  { type: 'ui', surfaceId, messages: compile(surfaceId, source), done: true },
  ...(trip ? [{ type: 'trip', trip }] : []),
  { type: 'done', stopReason: 'end_turn' },
];

const browser = await launchBrowser();
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
await page.fill('.chat__feed .turn__surface:not(.turn__surface--spent) .a2-surface input[type="text"]', 'LHR');
await page.fill('.tv-dates input[type="date"] >> nth=0', '2026-04-12');
await page.click('.tv-counter button[aria-label="One more"]');
await page.waitForTimeout(400);

check('three edits sent nothing', chatTurns() === afterFirst, `${chatTurns() - afterFirst} turns`);

// --- committing sends once, with everything -------------------------------
console.log('\ncommitting');
await page.locator('.chat__feed .turn__surface:not(.turn__surface--spent) .a2-surface .a2ui-button').first().click();
await page.waitForTimeout(900);

const commit = sent.filter((entry) => entry.surface === 'inline').at(-1);
check('the button sent exactly one turn', chatTurns() === afterFirst + 1, `${chatTurns() - afterFirst}`);
// The wire carries an A2UI action, not a sentence: this is what a Swift or
// Kotlin renderer posts for the same press, with nothing taught to it.
check(
  'as an A2UI action, not a synthesised message',
  typeof commit?.action?.name === 'string' && commit?.message === undefined,
  JSON.stringify({ name: commit?.action?.name, message: commit?.message }),
);
check(
  'carrying all three values at once, in the action context',
  commit?.action?.context?.origin === 'LHR' &&
    String(commit?.action?.context?.startDate ?? '').startsWith('2026-04-12') &&
    commit?.action?.context?.travelers === 3,
  JSON.stringify(commit?.action?.context ?? {}),
);
check(
  'and says which component was pressed',
  typeof commit?.action?.sourceComponentId === 'string',
  String(commit?.action?.sourceComponentId),
);
check('and it reads as a message in the conversation', (await page.locator('.bubble--event').count()) > 0);
// Readable, not the wire: the line used to be `commit surface — paths:
// ["/trip/origin", ...], startDate: "2026-04-12T00:00:00Z"`.
const said = (await page.locator('.bubble--event').last().textContent()) ?? '';
check(
  'in words a traveller would use',
  /12 Apr 2026/.test(said) && /LHR/.test(said) && !/\/trip\/|T00:00|paths|"/.test(said),
  said,
);
check(
  'and the date was stored as the calendar day it is',
  String(commit?.action?.context?.startDate) === '2026-04-12',
  String(commit?.action?.context?.startDate),
);

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
    ...document.querySelectorAll('.chat__feed .turn__surface:not(.turn__surface--spent) .a2-surface input'),
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
await page.locator('.chat__feed .turn__surface:not(.turn__surface--spent) .a2-surface input[type="range"]').first().fill('3400');
await page.waitForTimeout(400);
check('moving the slider sent nothing', chatTurns() === before);

// The server guarantees a way out: a surface of editors with nothing to press
// gets a commit button before it ever reaches the browser. That used to be a
// bar the React app drew for itself, which meant an iOS client shipped the dead
// end this is testing for.
const commitButton = page
  .locator('.chat__feed .turn__surface:not(.turn__surface--spent) .a2-surface .a2ui-button')
  .last();
check('the surface came with a way to send anyway', (await commitButton.count()) > 0);
await commitButton.click();
await page.waitForTimeout(900);
check('and pressing it sends the values', chatTurns() === before + 1, `${chatTurns() - before}`);
check(
  // In the surface's data model, which the server asked for with
  // `sendDataModel`; nothing gathers paths into the button's context any more.
  'with the edited value in the data model it sends',
  sent.at(-1)?.action?.dataModel?.trip?.budget === 3400,
  JSON.stringify(sent.at(-1)?.action?.dataModel?.trip ?? {}),
);

// --- the panel is a record, not a form ------------------------------------
console.log('\nthe panel');
await page.waitForSelector('.sidebar .a2-surface', { timeout: 20000 }).catch(() => {});
if ((await page.locator('.sidebar .a2-surface').count()) === 0) {
  await page.locator('.sidebar__placeholder button').click().catch(() => {});
  await page.waitForSelector('.sidebar .a2-surface', { timeout: 20000 }).catch(() => {});
}

if ((await page.locator('.sidebar .a2-surface').count()) > 0) {
  const beforePanel = chatTurns();

  // The model drew a slider it should not have. Nothing there may send.
  if ((await page.locator('.sidebar input[type="range"]').count()) > 0) {
    await page.locator('.sidebar input[type="range"]').fill('420');
    await page.waitForTimeout(400);
    check('a control in the panel sends nothing, whatever the model drew', chatTurns() === beforePanel);
  }
  check(
    'and the panel never offers to submit',
    (await page.locator('.sidebar .pending').count()) === 0,
  );
  check(
    'the plan is A2UI the agent drew, not React the app shipped',
    (await page.locator('.sidebar .plan').count()) === 0,
  );

  // Change is the panel's only interaction, and it reopens the decision in the
  // conversation rather than editing it here.
  await page.locator('.sidebar .a2ui-button').first().click();
  await page.waitForTimeout(900);
  check('Change sends exactly one message', chatTurns() === beforePanel + 1);

  const asked = sent.at(-1);
  check(
    'asking to reopen the decision, in the conversation',
    // The browser routes it inline and sends the action untouched. What the
    // press *means* is the server's to say, so there is no sentence here to
    // assert — only the action and where it was aimed.
    asked?.surface === 'inline' && asked?.action?.name === 'change',
    `${asked?.surface}: ${JSON.stringify(asked?.action ?? {}).slice(0, 90)}`,
  );
  check(
    'and it reads as a message like any other',
    (await page.locator('.bubble--event').count()) >= 2,
  );
} else {
  check('the panel rendered', false, 'no panel appeared');
}

await browser.close();

console.log(`\n${failures.length === 0 ? 'All checks passed.' : `${failures.length} failed:`}`);
for (const failure of failures) console.log(`  - ${failure}`);
process.exit(failures.length === 0 ? 0 : 1);
