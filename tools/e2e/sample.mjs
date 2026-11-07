#!/usr/bin/env node
/**
 * The sample trip a first visit opens on.
 *
 * A first visit opens on a recorded conversation with the agent (`tools/sample/record.py`), replayed through the handler a live
 * turn uses. This checks the parts a visitor depends on:
 *
 *   - it is there with no key, and nothing covers it;
 *   - it says it is a sample, at the top and on every turn it holds;
 *   - its cards and the panel are drawn, and its presses read as sentences;
 *   - it cost nothing: no turn is counted;
 *   - it is live — pressing a card with no key asks for one, and with a key the
 *     next turn carries the sample's trip, so the agent picks up from it;
 *   - and putting it away is one press, and it stays away.
 *
 * Starts its own scripted servers with `SAMPLE_TRIP=1`, because every other
 * suite runs with it off so that it starts from an empty conversation.
 *
 *   node tools/e2e/sample.mjs
 */

import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { launchBrowser } from '../browser.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const PYTHON = process.env.PYTHON ?? 'python3';

let failures = 0;
const ok = (label, condition, detail = '') => {
  if (condition) console.log(`  ok    ${label}`);
  else {
    failures += 1;
    console.log(`  FAIL  ${label}${detail ? ` — ${detail}` : ''}`);
  }
};

async function serve(port, key) {
  const env = { ...process.env, SAMPLE_TRIP: '1' };
  delete env.GEMINI_API_KEY;
  delete env.GOOGLE_API_KEY;
  if (key) env.GEMINI_API_KEY = key;
  const child = spawn(PYTHON, ['tools/e2e/scripted_server.py', String(port)], {
    cwd: root,
    env,
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  let stderr = '';
  child.stderr.on('data', (chunk) => (stderr += chunk));
  for (let attempt = 0; attempt < 60; attempt++) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/meta`);
      if (response.ok) return { child, base: `http://127.0.0.1:${port}/` };
    } catch {
      /* not up yet */
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  child.kill();
  throw new Error(`The server on ${port} never came up.\n${stderr.slice(-800)}`);
}

async function freshPage(browser, base) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(base);
  await page.evaluate(() => localStorage.clear());
  await page.goto(base);
  await page.waitForSelector('.topbar', { timeout: 30000 });
  await page.waitForSelector('.sample', { timeout: 15000 }).catch(() => {});
  return { page, context };
}

const browser = await launchBrowser();
const servers = [];

try {
  console.log('\n--- a first visit, with no key ---');
  const keyless = await serve(Number(process.env.SAMPLE_PORT ?? 8243), null);
  servers.push(keyless.child);
  {
    const { page, context } = await freshPage(browser, keyless.base);

    ok('the sample is there on arrival', (await page.locator('.sample').count()) === 1);
    ok('and nothing covers it', (await page.locator('.gate').count()) === 0);
    ok('it says it is a sample', /sample trip/i.test((await page.locator('.sample').textContent()) ?? ''));

    const users = page.locator('.bubble--user');
    const userCount = await users.count();
    const tagged = await page.locator('.bubble--sample').count();
    ok(
      'every turn in it is marked as the sample',
      userCount > 0 && tagged === userCount,
      `${tagged}/${userCount}`,
    );

    ok(
      'its cards are drawn',
      (await page.locator('.chat__feed .a2-surface').count()) >= 3,
      String(await page.locator('.chat__feed .a2-surface').count()),
    );
    ok('so is the panel beside it', (await page.locator('.sidebar__body .a2-surface').count()) === 1);
    ok(
      'and the panel says it is the sample',
      /sample/i.test((await page.locator('.sidebar__head').textContent()) ?? ''),
    );

    const presses = await page.locator('.bubble--event p').allTextContents();
    ok(
      'its presses read as sentences',
      presses.length > 0 && presses.every((line) => !/\/trip\/|T00:00|"|\b[a-z]+_[a-z]+\b/.test(line)),
      JSON.stringify(presses),
    );

    ok(
      'and it cost nothing',
      /no turns yet/.test((await page.locator('.statusbar').textContent()) ?? ''),
      (await page.locator('.statusbar').textContent()) ?? '',
    );

    // It is live: carrying on from it runs a model, and that asks. By pressing
    // the newest card when the agent drew something pressable there, and by
    // typing when it did not — a list of highlights is a fine last card.
    const press = page.locator('.chat__feed .turn__surface:not(.turn__surface--spent) .a2ui-button').first();
    const how = (await press.count()) > 0 ? 'pressing its newest card' : 'typing after it';
    if ((await press.count()) > 0) await press.click();
    else {
      await page.locator('.composer textarea').fill('make it three of us');
      await page.locator('.composer textarea').press('Enter');
    }
    await page.waitForSelector('.gate', { timeout: 5000 }).catch(() => {});
    ok(`carrying on from it (${how}) asks for a key`, (await page.locator('.gate').count()) === 1);
    await page.keyboard.press('Escape');
    const cancel = page.locator('.gate button', { hasText: /cancel|close|not now|later/i });
    if ((await cancel.count()) > 0) await cancel.first().click();
    await page.waitForTimeout(200);

    await page.locator('.sample__remove').click();
    await page.waitForTimeout(400);
    ok('it can be put away', (await page.locator('.sample').count()) === 0);
    ok('leaving an empty conversation', (await page.locator('.bubble--user').count()) === 0);
    ok('with the suggestions back', (await page.locator('.chat__intro').count()) === 1);

    await page.reload();
    await page.waitForSelector('.topbar', { timeout: 30000 });
    await page.waitForTimeout(1200);
    ok('and it stays away after a reload', (await page.locator('.sample').count()) === 0);

    await context.close();
  }

  console.log('\n--- carrying on from it, with a key on the server ---');
  const served = await serve(Number(process.env.SAMPLE_SERVED_PORT ?? 8244), 'scripted');
  servers.push(served.child);
  {
    const { page, context } = await freshPage(browser, served.base);
    const bodies = [];
    page.on('request', (request) => {
      if (request.url().endsWith('/api/chat')) bodies.push(JSON.parse(request.postData() ?? '{}'));
    });

    const composer = page.locator('.composer textarea');
    await composer.fill('make it three of us');
    await composer.press('Enter');
    await page.waitForTimeout(2500);

    const sent = bodies.at(-1);
    ok('a typed turn goes out', Boolean(sent), 'no request');
    ok(
      "carrying the sample's trip, so the agent picks up from it",
      sent?.resume?.trip?.origin === 'JFK' && Boolean(sent?.resume?.trip?.selectedHotel),
      JSON.stringify(sent?.resume?.trip ?? null).slice(0, 200),
    );
    ok('nobody is asked for a key', (await page.locator('.gate').count()) === 0);

    await context.close();
  }
} finally {
  await browser.close();
  for (const child of servers) child.kill();
}

console.log(`\n${failures ? `${failures} failure(s)` : 'All checks passed.'}`);
process.exit(failures ? 1 : 0);
