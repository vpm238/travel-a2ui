#!/usr/bin/env node
/**
 * The Flutter client, in a real browser, against the real server.
 *
 * The widget tests already prove the renderer draws the server's own bytes. What
 * they cannot prove is that the *client* works: that it fetches the catalog it
 * needs before drawing anything, reads a server-sent event stream, paints a
 * surface mid-turn, and sends a press back as an action rather than as a
 * sentence. All of that is the part between the widgets and the wire, and none
 * of it runs in a widget test.
 *
 * The model is scripted (`tools/e2e/scripted_server.py`), so this needs no API
 * key and costs nothing — which is the only way an end-to-end test actually
 * gets run.
 *
 * Flutter draws to a canvas, so there is no DOM to query. Its accessibility
 * tree is the way in: the framework ships a hidden button that turns semantics
 * on, and once it is clicked every piece of text is a real element that
 * Playwright can find. Clicking it is not a workaround — it is what a screen
 * reader does, and a surface a screen reader cannot see is a surface that fails
 * for the people generative UI is supposed to include.
 *
 *   node tools/e2e/flutter.mjs [--screenshot path.png]
 */

import { chromium } from 'playwright';

const ORIGIN = process.env.ORIGIN ?? 'http://127.0.0.1:8130';
const screenshotAt = process.argv.indexOf('--screenshot');
const screenshot = screenshotAt === -1 ? null : process.argv[screenshotAt + 1];

let failures = 0;
const check = (ok, what, detail = '') => {
  if (ok) {
    console.log(`  ✓ ${what}`);
  } else {
    failures += 1;
    console.log(`  ✗ ${what}${detail ? `\n      ${detail}` : ''}`);
  }
};

// Let Playwright find its own browser; `CHROMIUM_PATH` overrides it for an
// environment that keeps one somewhere else.
const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
);
const page = await browser.newPage({ viewport: { width: 900, height: 1100 } });

/**
 * What a screen reader would actually read.
 *
 * Flutter splits its accessibility tree two ways: some nodes carry their text
 * as DOM text, and some — anything the framework merges into one node, which
 * is most plain text inside a card — carry it as an `aria-label` instead.
 * Reading only `innerText` therefore misses whole headings while the surface
 * is plainly on screen, which looks exactly like a rendering bug and is not
 * one. Both halves together are the readable page.
 */
const readable = () =>
  page.evaluate(() =>
    [
      document.body.innerText,
      ...[...document.querySelectorAll('[aria-label]')].map((el) =>
        el.getAttribute('aria-label'),
      ),
    ].join('\n'),
  );

/** Every request the client makes, so the boot sequence can be asserted. */
const requested = [];
page.on('request', (request) => requested.push(request.url().replace(ORIGIN, '')));

const failed = [];
page.on('pageerror', (error) => failed.push(String(error)));
page.on('console', (message) => {
  if (message.type() === 'error') failed.push(message.text());
});

try {
  console.log('\nBooting');
  await page.goto(`${ORIGIN}/flutter/`, { waitUntil: 'domcontentloaded' });

  // Flutter takes a moment to boot its engine; waiting for the canvas is the
  // honest signal that it has.
  await page.waitForSelector('flt-glass-pane, flutter-view, canvas', { timeout: 60_000 });
  check(true, 'the engine started');

  // Semantics on, so there is something to assert against.
  //
  // Dispatched from the page rather than clicked through Playwright: the
  // placeholder is a 1×1 element parked at (-1, -1), which is outside the
  // viewport, and a real click is refused for exactly that reason. What the
  // framework listens for is the click event itself.
  await page.evaluate(() => document.querySelector('flt-semantics-placeholder')?.click());
  await page.waitForTimeout(1500);

  const bootText = await readable().catch(() => '');
  check(
    bootText.includes('Describe a trip') || bootText.includes('Travel A2UI'),
    'the app rendered its opening screen',
    bootText.slice(0, 200),
  );

  check(
    requested.some((url) => url.startsWith('/api/meta')),
    'it asked the server what it is',
  );
  check(
    requested.some((url) => url.startsWith('/api/catalog')),
    'it fetched the catalog rather than shipping one',
  );

  console.log('\nA turn');
  // The composer is a real text field once semantics are on.
  const field = page.locator('input, textarea, [role="textbox"]').first();
  await field.click({ timeout: 30_000 });
  await field.fill('flights to Madrid');
  await page.keyboard.press('Enter');

  // The skeleton goes out before the search returns, so a surface exists well
  // before the turn ends. Waiting for the heading is waiting for that.
  await page.waitForFunction(
    () =>
      [...document.querySelectorAll('[aria-label]')]
        .map((el) => el.getAttribute('aria-label'))
        .concat(document.body.innerText)
        .join('\n')
        .includes('Flights to Madrid'),
    { timeout: 60_000 },
  );
  check(true, 'a surface painted during the turn');

  await page.waitForTimeout(2500);
  const after = await readable();

  check(after.includes('Looking at flights'), 'the prose arrived');
  check(/United|Lufthansa/.test(after), 'the flights filled in', after.slice(0, 400));

  // Asserted against the labels rather than the whole page, because the app's
  // own header also says "Sample data" — reading the page as one string lets
  // the chrome answer for the surface, and the check passes with no surface
  // at all.
  const labels = await page.evaluate(() =>
    [...document.querySelectorAll('[aria-label]')].map((el) => el.getAttribute('aria-label')),
  );
  check(
    labels.some((label) => label?.includes('Sample data')),
    'and the surface itself says the data is generated',
    labels.join(' | '),
  );

  // Four options, as the fixtures return.
  const fares = after.match(/\$\d{2,4}/g) ?? [];
  check(fares.length >= 4, `four fares are on screen (found ${fares.length})`, fares.join(' '));

  console.log('\nPressing a flight');
  const before = requested.filter((url) => url.startsWith('/api/chat')).length;
  // Pressed through the accessibility tree, which is the point: a flight card
  // is only selectable if it reached that tree as a button. Clicking painted
  // pixels by coordinate would pass whether or not it did.
  const cards = page.locator('flt-semantics[role="button"]', { hasText: 'United' });
  await cards.first().click({ timeout: 30_000 });
  await page.waitForTimeout(2000);

  const chats = requested.filter((url) => url.startsWith('/api/chat')).length;
  check(chats > before, 'the press became the next turn');

  if (screenshot) {
    await page.screenshot({ path: screenshot, fullPage: true });
    console.log(`\n  screenshot: ${screenshot}`);
  }

  check(failed.length === 0, 'no errors in the console', failed.slice(0, 3).join('\n      '));
} catch (error) {
  failures += 1;
  console.log(`\n  ✗ ${error.message}`);
  if (screenshot) await page.screenshot({ path: screenshot, fullPage: true }).catch(() => {});
} finally {
  await browser.close();
}

console.log(failures === 0 ? '\nAll checks passed.\n' : `\n${failures} check(s) failed.\n`);
process.exit(failures === 0 ? 0 : 1);
