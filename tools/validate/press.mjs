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

// Wait for fares to appear.
await page.locator('.a2-flight, [class*="flight" i]').first().waitFor({ timeout: 240000 });
await page.waitForTimeout(6000);

const shot = process.env.SHOTS ?? '/tmp/shots';
await page.screenshot({ path: `${shot}/1-outbound.png`, fullPage: true });

const fares = page.locator('.a2-flight, [class*="flight" i]');
console.log('fare cards on screen:', await fares.count());
await fares.first().click();

await page.waitForTimeout(25000);
await page.screenshot({ path: `${shot}/2-after-press.png`, fullPage: true });

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
