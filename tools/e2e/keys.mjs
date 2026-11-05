#!/usr/bin/env node
/**
 * The app with no key, and with only the server's key.
 *
 * Every other browser check runs against a scripted server started with
 * `GEMINI_API_KEY=scripted`, so the server always has a key and the browser
 * never needs one. Both states this file covers were therefore untested, and
 * both were broken:
 *
 *   keyless   The key form mounted on page load as a full-screen overlay with
 *             no way to close it, over the Catalog and Wire tabs — the two
 *             views that run no model, which the README sends people to first
 *             precisely because they need no key.
 *
 *   server    With a key on the server and none in the browser, "Set up" did
 *             nothing and the microphone said "Add your Gemini key first",
 *             because three paths checked for a *browser* key and ignored the
 *             server's — though every door falls back to it, and typed turns
 *             already worked.
 *
 * Starts its own two servers rather than taking a URL, because the thing under
 * test is what the server does or does not hold.
 *
 *   node tools/e2e/keys.mjs
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

/** A scripted server with or without a key of its own, ready to serve. */
async function serve(port, key) {
  const env = { ...process.env };
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

/** A page with nothing stored: no key, no session, no remembered tab. */
async function freshPage(browser, base) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(base);
  await page.evaluate(() => localStorage.clear());
  await page.goto(base);
  await page.waitForSelector('.topbar', { timeout: 30000 });
  // `/api/meta` decides which state the app is in; let it land.
  await page.waitForTimeout(800);
  return { page, context };
}

const tab = (page, name) => page.locator('.topbar__views button', { hasText: name });

/**
 * Clicks a tab and says whether it opened.
 *
 * A short timeout and a caught error, because the failure this file exists for
 * is an overlay intercepting the click — and Playwright reports that by timing
 * out, which would otherwise end the run on the first check with a stack trace
 * instead of a line saying which tab was unreachable.
 */
async function opens(page, name) {
  try {
    await tab(page, name).click({ timeout: 3000 });
  } catch {
    return false;
  }
  await page.waitForTimeout(300);
  return (await tab(page, name).getAttribute('aria-current')) === 'true';
}

const browser = await launchBrowser();
const servers = [];

try {
  // ------------------------------------------------------------- no key at all
  console.log('\n--- no key anywhere ---');
  const keyless = await serve(Number(process.env.KEYLESS_PORT ?? 8241), null);
  servers.push(keyless.child);
  {
    const { page, context } = await freshPage(browser, keyless.base);

    ok('nothing covers the page on arrival', (await page.locator('.gate').count()) === 0);

    ok('the Catalog tab opens without a key', await opens(page, 'Catalog'), 'something covers it');
    ok('the Wire tab opens without a key', await opens(page, 'Wire'), 'something covers it');

    // Running a model is what asks.
    await opens(page, 'Chat');
    const composer = page.locator('.composer textarea');
    await composer.fill('A week in Madrid from JFK for two');
    await composer.press('Enter');
    await page.waitForSelector('.gate', { timeout: 10000 }).catch(() => {});
    ok('sending a message asks for a key', (await page.locator('.gate').count()) === 1);

    // And the question can be put down again.
    const close = page.locator('.gate button', { hasText: /close|cancel|not now|later/i });
    if ((await close.count()) > 0) await close.first().click();
    else await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    ok('the key form can be dismissed', (await page.locator('.gate').count()) === 0);

    await context.close();
  }

  // --------------------------------------------------- the server's key only
  console.log('\n--- a key on the server, none in the browser ---');
  const served = await serve(Number(process.env.SERVED_PORT ?? 8242), 'scripted');
  servers.push(served.child);
  {
    const { page, context } = await freshPage(browser, served.base);

    ok('no key form for a server that has one', (await page.locator('.gate').count()) === 0);

    // The app warms on its own when it can; if it is still cold, "Set up" must
    // actually do something rather than return on an empty browser key.
    const setUp = page.locator('.banner__action', { hasText: /set up/i });
    if ((await setUp.count()) > 0) await setUp.click();
    await page
      .waitForFunction(
        () => /ready|getting ready/i.test(document.querySelector('.warmth')?.textContent ?? ''),
        { timeout: 15000 },
      )
      .catch(() => {});
    const warmth = (await page.locator('.warmth').textContent().catch(() => '')) ?? '';
    ok('setting up opens a conversation', /ready|getting ready/i.test(warmth), `warmth: "${warmth}"`);

    const composer = page.locator('.composer textarea');
    await composer.fill('A week in Madrid from JFK for two');
    await composer.press('Enter');
    await page.waitForSelector('.turn', { timeout: 30000 }).catch(() => {});
    ok('a typed turn is answered on the server key', (await page.locator('.turn').count()) > 0);
    ok('and nobody is asked for a key', (await page.locator('.gate').count()) === 0);

    await context.close();
  }
} finally {
  await browser.close();
  for (const child of servers) child.kill();
}

console.log(`\n${failures ? `${failures} failure(s)` : 'All checks passed.'}`);
process.exit(failures ? 1 : 0);
