#!/usr/bin/env node
/**
 * The quickstart's "what is A2UI on this screen" picture, from the running app.
 *
 * Opens the recorded sample trip (no key needed), outlines every A2UI surface
 * in blue and the app's own fixed parts in grey, and saves the result.
 *
 *   ./scripts/quickstart.sh react                      # in another terminal
 *   node tools/screenshots/quickstart.mjs
 *
 * BASE_URL picks another server; the first argument another output file.
 */

import { launchBrowser } from '../browser.mjs';

const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8080/';
const OUT = process.argv[2] ?? 'docs/site/src/assets/quickstart/a2ui-vs-app.png';

const browser = await launchBrowser();
const page = await (
  await browser.newContext({ viewport: { width: 1280, height: 1000 }, deviceScaleFactor: 2 })
).newPage();
await page.goto(BASE, { waitUntil: 'networkidle' });
await page.waitForSelector('.a2-surface[data-surface="sidebar"]');
await page.waitForTimeout(1500);

// The most recent card that fits on screen whole, just below the header, with
// the reply after it.
await page.evaluate(() => {
  const room =
    document.querySelector('.composer').getBoundingClientRect().top -
    document.querySelector('.topbar').getBoundingClientRect().bottom;
  const inline = [...document.querySelectorAll('.a2-surface')].filter(
    (el) => el.dataset.surface !== 'sidebar',
  );
  const card =
    [...inline].reverse().find((el) => el.getBoundingClientRect().height < room - 200) ?? inline.at(-1);
  if (!card) return;
  card.style.scrollMarginTop = '90px';
  // Instantly, so the outlines below are measured where the content comes to rest.
  document.querySelector('.chat__feed').style.scrollBehavior = 'auto';
  card.scrollIntoView({ block: 'start', behavior: 'instant' });
});
await page.waitForTimeout(1500);

const marked = await page.evaluate(() => {
  const top = document.querySelector('.topbar').getBoundingClientRect().bottom;
  const bottom = document.querySelector('.composer').getBoundingClientRect().top;
  const kinds = {
    a2ui: { color: '#1f6feb', line: 'solid' },
    app: { color: '#6b7280', line: 'dashed' },
  };
  const boxes = [
    // Composed by the agent: A2UI surfaces.
    ...[...document.querySelectorAll('.a2-surface')].map((el) => ({
      el,
      kind: 'a2ui',
      label: `A2UI surface · ${el.dataset.surface}`,
      inFeed: el.dataset.surface !== 'sidebar',
    })),
    // The app's own code, the same on every turn.
    { el: document.querySelector('.topbar'), kind: 'app', label: 'App code · header and tabs' },
    { el: document.querySelector('.composer'), kind: 'app', label: 'App code · message box' },
    // The model's words, drawn by the app as plain text.
    ...[...document.querySelectorAll('.bubble--agent')].map((el) => ({
      el,
      kind: 'app',
      label: 'Plain text · not A2UI',
      inFeed: true,
    })),
  ];
  let count = 0;
  for (const { el, kind, label, inFeed } of boxes) {
    if (!el) continue;
    const rect = el.getBoundingClientRect();
    if (rect.height < 24) continue;
    // Only what is wholly on screen, so no outline is cut off by the header or the message box.
    if (inFeed && (rect.top < top + 8 || rect.bottom > bottom - 8)) continue;
    if (!inFeed && (rect.top < 0 || rect.bottom > innerHeight)) continue;
    const { color, line } = kinds[kind];
    const frame = document.createElement('div');
    Object.assign(frame.style, {
      position: 'fixed',
      left: `${rect.left - 4}px`,
      top: `${rect.top - 4}px`,
      width: `${rect.width + 8}px`,
      height: `${rect.height + 8}px`,
      border: `3px ${line} ${color}`,
      borderRadius: '12px',
      pointerEvents: 'none',
      zIndex: 9999,
    });
    const tag = document.createElement('span');
    tag.textContent = label;
    Object.assign(tag.style, {
      position: 'absolute',
      right: '12px',
      // On the bottom edge for anything at the very top of the window.
      ...(rect.top < 20 ? { bottom: '-14px' } : { top: '-14px' }),
      padding: '3px 8px',
      borderRadius: '6px',
      background: color,
      color: '#fff',
      whiteSpace: 'nowrap',
      font: '600 13px/1.3 system-ui, sans-serif',
    });
    frame.append(tag);
    document.body.append(frame);
    count++;
  }
  return count;
});

await page.screenshot({ path: OUT });
await browser.close();
console.log(`Marked ${marked} regions → ${OUT}`);
