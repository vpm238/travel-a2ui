/**
 * The real client, pressing a fare the moment it appears.
 *
 * `tools/validate/journey.py` posts to `/api/chat` itself, so it has never
 * exercised what the *browser* sends — the receipt it carries, the surface's
 * data model, the session id — nor what it does to a turn still streaming when
 * somebody presses something. That gap hid a real bug for a day: the receipt
 * and the session write both happened after the sidebar rebuild, so pressing a
 * fare as soon as it drew aborted the stream before either landed, and the next
 * turn ran against an empty trip and asked for the route, the dates and the
 * party all over again.
 *
 * So this drives Chromium against the app, presses the first fare as soon as it
 * can see one, and prints every request body.
 *
 *   GEMINI_API_KEY=… BASE_URL=http://127.0.0.1:8787 node tools/validate/press.mjs
 *
 * It costs real money and needs a browser, so it is not in CI.
 */
import { chromium } from 'playwright';

const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8191';
const KEY = process.env.GEMINI_API_KEY ?? '';
const PROMPT =
  'A trip for two from Copenhagen to Berlin, leaving next monday, coming back next thursday, ' +
  'but only one person on the way back. Include hotel close to Kurfürstendamm.';

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
  // The session's egress proxy terminates TLS with its own CA, which Chromium
  // does not carry. Only used to reach our own deployment from inside here.
  args: ['--ignore-certificate-errors'],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 1600 }, ignoreHTTPSErrors: true });

const sent = [];
page.on('request', (request) => {
  if (request.method() !== 'POST' || !request.url().includes('/api/chat')) return;
  try {
    sent.push(JSON.parse(request.postData() ?? '{}'));
  } catch {
    /* ignore */
  }
});

await page.addInitScript((key) => {
  try {
    // The name the app actually reads — see `API_KEY` in useAgent.ts.
    window.localStorage.setItem('travel-a2ui:key', key);
  } catch {
    /* ignore */
  }
}, KEY);

await page.goto(BASE, { waitUntil: 'networkidle' });

const box = page.locator('textarea, input[type="text"]').last();
await box.waitFor({ timeout: 20000 });
await box.fill(PROMPT);
await page.keyboard.press('Enter');

// Everything pressed here is scoped to the conversation column, and within it
// to the *live* card: `.turn__surface--spent` is how the client marks a card the
// turn has moved past. Page-wide selectors read the panel too, which has an
// "Outbound flight — … Change" row on it, and the first run of this script
// pressed that Change link instead of the return fare and measured nothing.
const FEED = '.chat__feed';
const LIVE = `${FEED} .turn__surface:not(.turn__surface--spent)`;
const SPENT = `${FEED} .turn__surface--spent`;
// Option rows, not the boxes around them: the renderer's class names repeat
// down the tree, so a bare match counts a card several times over.
const leaf = (word) => `[class*="${word}" i]:not(:has([class*="${word}" i]))`;

/** Wait until the live card holds options of this kind, or give up. */
async function liveOptions(word, timeout = 240000) {
  const rows = page.locator(`${LIVE} ${leaf(word)}`);
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    if (await rows.count()) return rows;
    await page.waitForTimeout(2000);
  }
  return null;
}

// Wait for fares to appear.
const fares = (await liveOptions('flight')) ?? page.locator(`${LIVE} ${leaf('flight')}`);
await page.waitForTimeout(6000);

const shot = process.env.SHOTS ?? '/tmp/shots';
await page.screenshot({ path: `${shot}/1-outbound.png`, fullPage: true });

console.log('fare cards on the live card:', await fares.count());

// The panel *before* anything is pressed. "Why does the sidebar not start to
// build until I select the first flight" is this line coming back empty.
const before = await page.locator('aside, [class*="sidebar" i]').first().innerText().catch(() => '');
console.log('\n=== the panel, before the press ===');
console.log(before.slice(0, 260) || '(nothing)');
await fares.first().click();

await page.waitForTimeout(25000);
await page.screenshot({ path: `${shot}/2-after-press.png`, fullPage: true });

// Carry on to the stay, and watch whether the card survives being pressed.
//
// "Sometimes selecting the hotel makes the hotel disappear." A turn draws onto
// the surface it was given, so every card pressed should stay exactly where it
// is — greyed, with the choice still on it. This walks outbound → return → stay
// and checks each spent card still holds what was picked from it.
if (process.env.THROUGH_TO_HOTEL) {
  /** Press the first option of a kind on the live card; report what survived. */
  async function pick(word, label) {
    const rows = await liveOptions(word);
    if (!rows) {
      console.log(`\n${label}: nothing to press — the turn never drew one`);
      return null;
    }
    const before = await rows.count();
    const chosen = ((await rows.first().innerText()) || '').split('\n')[0]?.trim();
    console.log(`\n${label}: ${before} on the live card, pressing "${chosen}"`);
    await rows.first().click();
    // The press ends the turn that drew the card, so the card goes spent. Wait
    // for that rather than for a fixed number of seconds.
    await page
      .locator(SPENT)
      .last()
      .waitFor({ timeout: 60000 })
      .catch(() => {});
    await page.waitForTimeout(20000);
    const kept = page.locator(`${SPENT}:has-text("${chosen}") ${leaf(word)}`);
    const after = await kept.count();
    console.log(
      after >= before
        ? `ok — the card pressed still shows all ${after} of them`
        : `FAIL — the card pressed went from ${before} to ${after}: ${label} disappeared`,
    );
    return chosen;
  }

  await pick('flight', 'return flights');
  await pick('hotel', 'stays');
  await page.screenshot({ path: `${shot}/3-after-hotel.png`, fullPage: true });
}

console.log('\n=== what the browser sent ===');
for (const [index, body] of sent.entries()) {
  const kind = body.action ? `press ${body.action.name}` : `say ${JSON.stringify(body.message ?? '').slice(0, 60)}`;
  console.log(`\n-- POST ${index + 1}: ${kind}`);
  console.log('   sessionId      :', body.sessionId);
  console.log('   surfaceId      :', body.surfaceId ?? '(server picks)');
  console.log('   resume.trip    :', JSON.stringify(body.resume?.trip ?? null));
  console.log('   resume.interaction:', (body.resume?.interactionId ?? '').slice(0, 24));
  console.log('   resume.setup   :', body.resume?.setup);
  if (body.action) {
    console.log('   action.context :', JSON.stringify(body.action.context));
    console.log('   action.surface :', body.action.surfaceId);
    console.log('   action.dataModel.trip:', JSON.stringify(body.action.dataModel?.trip ?? null));
  }
}

const text = await page.locator('body').innerText();
console.log('\n=== the turn after the press, as text ===');
console.log(text.split('FROM THE INTERFACE').pop()?.slice(0, 700));
// Is there a panel beside the conversation, and does it know the trip?
const panel = await page.locator('aside, [class*="sidebar" i]').first().innerText().catch(() => '');
console.log('\n=== the panel, right after the press ===');
console.log(panel.slice(0, 420) || '(nothing)');

// Only the conversation column. The panel's calendar is the *record* of the
// dates — read-only, and the right thing to show — so looking at the whole page
// reports a question wherever the trip has dates at all.
const said = await page.locator('.turn, [class*="turn" i]').allInnerTexts().catch(() => []);
const conversation = said.join('\n');
const asking = /mm\/dd\/yyyy|Trip dates|Travel dates|Set trip details/i.test(conversation);
console.log('\n=== does the conversation ask for dates again? ===');
console.log(asking ? 'FAIL — a date control is in the conversation after the press' : 'ok — no date control after the press');
process.exitCode = asking ? 1 : 0;

await browser.close();
