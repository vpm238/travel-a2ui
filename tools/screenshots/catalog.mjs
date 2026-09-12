#!/usr/bin/env node
/**
 * The catalog, as a page you can look at.
 *
 * A component reference that describes components in prose is a reference
 * nobody trusts, because the only way to know what `FlightOption` looks like is
 * to run it. So this drives the real gallery in a real browser, screenshots
 * each component as the renderer actually draws it, and writes a page pairing
 * that picture with the one line of Express that produced it and the props the
 * catalog declares.
 *
 * Everything on the page is generated from `catalog.json` and the gallery
 * build, so it cannot drift: add a component and it appears, change a prop and
 * the table changes, rename one and the old entry disappears. The alternative —
 * a hand-written table of props — is a document that is wrong within a month
 * and confidently so.
 *
 *   node tools/screenshots/catalog.mjs            # write docs/catalog/
 *   node tools/screenshots/catalog.mjs --check    # fail if anything is stale
 *
 * Needs the gallery built (`npm run build`) and a browser. Light and dark are
 * both captured because a component that only works on one is a component that
 * is broken for half the people who open it.
 */

import { createServer } from 'node:http';
import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync, rmSync } from 'node:fs';
import { dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { launchBrowser } from '../browser.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
// The gallery is its own build — a standalone page, so the reference can be
// regenerated without the app or a Worker running.
const DIST = join(ROOT, 'apps', 'gallery', 'dist');
const OUT = join(ROOT, 'docs', 'catalog');
const PAGE = join(ROOT, 'docs', 'catalog.md');

const CHECK = process.argv.includes('--check');

const catalog = JSON.parse(readFileSync(join(ROOT, 'catalogs', 'a2ui-travel', 'catalog.json'), 'utf8'));
const allow = JSON.parse(
  readFileSync(join(ROOT, 'catalogs', 'a2ui-travel', 'agent-components.json'), 'utf8'),
);
const previews = JSON.parse(
  readFileSync(join(ROOT, 'apps', 'gallery', 'src', 'components.generated.json'), 'utf8'),
);

const MIME = {
  '.html': 'text/html',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
};

/** Serves the built app so the gallery runs exactly as it ships. */
function serve(port) {
  const server = createServer((request, response) => {
    const path = decodeURIComponent(new URL(request.url, 'http://x').pathname);
    const file = join(DIST, path === '/' ? 'index.html' : path);
    try {
      const body = readFileSync(file);
      response.writeHead(200, { 'content-type': MIME[extname(file)] ?? 'application/octet-stream' });
      response.end(body);
    } catch {
      // Single-page fallback, so /gallery routes to the shell like it does live.
      response.writeHead(200, { 'content-type': 'text/html' });
      response.end(readFileSync(join(DIST, 'gallery.html')));
    }
  });
  return new Promise((ready) => server.listen(port, '127.0.0.1', () => ready(server)));
}

/**
 * The declared props of one component, as rows for the reference table.
 *
 * A catalog component is an `allOf` of shared fragments plus its own object —
 * `ComponentCommon`, `Checkable`, and then the properties that are actually
 * about this component. Reading `schema.properties` alone finds nothing, which
 * is how the first version of this page shipped with no tables at all.
 */
function propsOf(name) {
  const schema = catalog.components?.[name];
  const parts = [schema, ...(schema?.allOf ?? [])].filter(Boolean);

  const properties = {};
  const required = new Set();
  for (const part of parts) {
    Object.assign(properties, part.properties ?? {});
    for (const key of part.required ?? []) required.add(key);
  }

  return Object.entries(properties)
    .filter(([key]) => key !== 'id' && key !== 'component')
    .map(([key, value]) => ({
      name: key,
      required: required.has(key),
      type: typeOf(value),
      options: value.enum ?? value.oneOf?.flatMap((entry) => entry.enum ?? []) ?? null,
      description: (value.description ?? '').replace(/\s+/g, ' ').trim(),
    }));
}

function typeOf(value) {
  if (value.enum) return 'one of';
  if (value.$ref) {
    const leaf = String(value.$ref).split('/').pop() ?? '';
    // The spec's dynamic types are the interesting distinction: a `DynamicString`
    // is where a binding can go, which is what a reader wants to know.
    return leaf.replace(/^Dynamic/, 'bindable ').toLowerCase();
  }
  return value.type ?? 'any';
}

const escape = (text) => text.replace(/\|/g, '\\|');

function markdown(captured) {
  const excluded = allow.excluded ?? {};
  const lines = [
    '# The travel catalog',
    '',
    `${captured.length} components, every one drawn here by the renderer that ships — not a`,
    'mockup. Each picture is a screenshot of the real component, beside the single line',
    'of A2UI Express that produced it.',
    '',
    'This page is generated from `catalogs/a2ui-travel/catalog.json` and the gallery',
    'build (`node tools/screenshots/catalog.mjs`), so it cannot describe a component',
    'that no longer exists or miss a prop that was added.',
    '',
    '**Lifting one of these.** A component is three things: an entry in the catalog',
    'schema, a React function in `packages/renderer/src/components/`, and whatever the',
    'skill says about when to use it. Copy all three and it works in another A2UI',
    'project — nothing here is coupled to travel except the names.',
    '',
    '---',
    '',
  ];

  for (const entry of captured) {
    lines.push(`## ${entry.name}`, '');
    if (entry.description) lines.push(entry.description, '');
    lines.push(
      '<picture>',
      `  <source media="(prefers-color-scheme: dark)" srcset="catalog/${entry.name}-dark.png">`,
      `  <img src="catalog/${entry.name}-light.png" alt="${entry.name} as the renderer draws it" width="560">`,
      '</picture>',
      '',
      '```',
      entry.express,
      '```',
      '',
    );

    const props = propsOf(entry.name);
    if (props.length > 0) {
      lines.push('| prop | type | | what it is |', '| --- | --- | --- | --- |');
      for (const prop of props) {
        const type = prop.options ? `\`${prop.options.join('` \\| `')}\`` : prop.type;
        lines.push(
          `| \`${prop.name}\` | ${escape(type)} | ${prop.required ? '**required**' : ''} | ${escape(prop.description)} |`,
        );
      }
      lines.push('');
    }
  }

  if (Object.keys(excluded).length > 0) {
    lines.push(
      '---',
      '',
      '## Drawn, but never offered to the model',
      '',
      'Every renderer keeps its full component registry; the *prompt* is pruned. These',
      'exist and work — a host can send them — but the agent is never told about them,',
      'because a catalog the model does not need is tokens on every single turn.',
      '',
      '| component | why it is pruned |',
      '| --- | --- |',
    );
    for (const [name, why] of Object.entries(excluded)) {
      lines.push(`| \`${name}\` | ${escape(String(why))} |`);
    }
    lines.push('');
  }

  return lines.join('\n');
}

async function main() {
  if (!existsSync(DIST)) {
    console.error('Build first: npm run build');
    process.exit(2);
  }

  const server = await serve(4183);
  const browser = await launchBrowser();

  const wanted = previews.filter((preview) => allow.allowedComponents.includes(preview.name));
  const captured = [];

  if (!CHECK) {
    // Removed rather than overwritten: a renamed component would otherwise
    // leave its old picture behind, and a stale screenshot is worse than none.
    rmSync(OUT, { recursive: true, force: true });
    mkdirSync(OUT, { recursive: true });
  }

  for (const scheme of ['light', 'dark']) {
    const page = await browser.newPage({
      viewport: { width: 900, height: 700 },
      colorScheme: scheme,
      deviceScaleFactor: 2,
    });
    await page.goto('http://127.0.0.1:4183/gallery.html', { waitUntil: 'networkidle' });

    for (const preview of wanted) {
      await page.getByRole('button', { name: preview.name, exact: true }).click();
      const article = page.locator('.gallery__component .gallery__surface');
      await article.waitFor({ state: 'attached' });
      // Attached rather than visible: a component that renders nothing has zero
      // height and never becomes "visible", and the right response to that is a
      // named failure rather than a 30-second timeout on the first one.
      const box = await article.boundingBox();
      if (!box || box.height < 4) {
        console.error(`  ${preview.name} rendered nothing — its example draws an empty component.`);
        process.exitCode = 1;
        continue;
      }
      // Let webfonts and any image settle, so two runs of this produce the same
      // bytes and `--check` means something.
      await page.waitForTimeout(180);

      const file = join(OUT, `${preview.name}-${scheme}.png`);
      if (CHECK) {
        if (!existsSync(file)) {
          console.error(`Missing screenshot: ${preview.name}-${scheme}.png`);
          process.exitCode = 1;
        }
      } else {
        await article.screenshot({ path: file });
      }

      if (scheme === 'light') {
        captured.push({
          name: preview.name,
          express: preview.express,
          description: (catalog.components?.[preview.name]?.description ?? '')
            .replace(/\s+/g, ' ')
            .trim(),
        });
      }
    }
    await page.close();
  }

  await browser.close();
  server.close();

  const body = markdown(captured);
  if (CHECK) {
    const current = existsSync(PAGE) ? readFileSync(PAGE, 'utf8') : '';
    if (current !== body) {
      console.error('docs/catalog.md is stale. Regenerate: node tools/screenshots/catalog.mjs');
      process.exitCode = 1;
    }
    if (!process.exitCode) console.log(`docs/catalog.md and ${wanted.length} components are current.`);
    return;
  }

  writeFileSync(PAGE, body);
  console.log(
    `wrote docs/catalog.md and ${readdirSync(OUT).length} screenshots for ${wanted.length} components`,
  );
}

await main();
