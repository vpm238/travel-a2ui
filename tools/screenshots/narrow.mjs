#!/usr/bin/env node
/**
 * Every component, at the widths it is actually drawn at.
 *
 * The reference captures each component in one frame, which is the one width
 * nobody sees it at: an inline card lives in a chat column, and the panel is a
 * sidebar. A card that looks composed at 1,600px and breaks at 320px is a card
 * that is broken, and the reference would never have shown it.
 *
 * So this drives the same `/catalog/<Name>` pages at the real widths and *measures* rather than
 * squints: a node whose content is wider than its box is reported with the
 * overflow in pixels. Optionally screenshots them too.
 *
 *   node tools/screenshots/narrow.mjs             # report overflows
 *   node tools/screenshots/narrow.mjs --shots     # and write docs/catalog/narrow/
 *
 * Exit code 1 when anything overflows, so this can be a check.
 */

import { createServer } from 'node:http';
import { readFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { launchBrowser } from '../browser.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const DIST = join(ROOT, 'apps', 'web', 'dist');
const OUT = join(ROOT, 'docs', 'catalog', 'narrow');
const SHOTS = process.argv.includes('--shots');

/** The widths this app actually renders components at. */
const WIDTHS = [
  { name: 'panel', width: 320 },
  { name: 'inline', width: 560 },
];

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
};

function serve(port) {
  const server = createServer((request, response) => {
    const path = (request.url ?? '/').split('?')[0];
    // Single-page fallback: /catalog/<Name> is a route the app knows.
    const asked = join(DIST, path.slice(1));
    const file = path !== '/' && existsSync(asked) ? asked : join(DIST, 'index.html');
    response.writeHead(200, { 'content-type': TYPES[extname(file)] ?? 'application/octet-stream' });
    response.end(readFileSync(file));
  });
  return new Promise((ready) => server.listen(port, () => ready(server)));
}

if (!existsSync(DIST)) {
  console.error('Build first: npm run build');
  process.exit(2);
}

const server = await serve(4184);
const browser = await launchBrowser();

// The same list the reference uses: every component the catalog declares and
// the pruner allows, so this cannot quietly stop covering one.
const previews = JSON.parse(
  readFileSync(join(ROOT, 'apps', 'web', 'src', 'generated', 'catalog-reference.json'), 'utf8'),
).components;

let bad = 0;

for (const { name, width } of WIDTHS) {
  const page = await browser.newPage({ viewport: { width: width + 80, height: 1200 } });
  const overflows = [];
  for (const preview of previews) {
    await page.goto(`http://127.0.0.1:4184/catalog/${preview.name}`, { waitUntil: 'networkidle' });
    // Narrow the stage to the width under test. The components inside have to
    // cope with it, which is the whole question.
    await page.addStyleTag({
      content: `.specimen__surface { width: ${width}px !important; max-width: ${width}px !important; }`,
    });
    const stage = page.locator('.specimen__surface');
    await stage.waitFor({ state: 'attached' });
    await page.waitForTimeout(60);

    const found = await page.evaluate(() => {
      const stage = document.querySelector('.specimen__surface');
      if (!stage) return null;
      const worst = { node: '', over: 0 };
      for (const node of [stage, ...stage.querySelectorAll('*')]) {
        const over = node.scrollWidth - node.clientWidth;
        if (over <= 1 || node.clientWidth === 0) continue;
        const style = getComputedStyle(node);
        if (style.overflowX === 'auto' || style.overflowX === 'scroll') continue;
        if (over > worst.over) {
          worst.over = over;
          worst.node = `${node.tagName.toLowerCase()}.${String(node.className || '').split(' ')[0]}`;
        }
      }
      return worst.over > 1 ? worst : null;
    });

    if (found) overflows.push({ component: preview.name, ...found });

    if (SHOTS) {
      mkdirSync(OUT, { recursive: true });
      await stage.screenshot({ path: join(OUT, `${preview.name}-${name}.png`) }).catch(() => {});
    }
  }

  console.log(`\n${name} (${width}px): ${overflows.length ? `${overflows.length} of ${previews.length} overflow` : `all ${previews.length} clean`}`);
  for (const entry of overflows) {
    console.log(`  ${entry.component.padEnd(18)} ${entry.node.padEnd(30)} +${entry.over}px`);
  }
  bad += overflows.length;
  await page.close();
}

await browser.close();
server.close();
process.exit(bad ? 1 : 0);
