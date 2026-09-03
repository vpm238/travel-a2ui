#!/usr/bin/env node
/**
 * Compiles the surfaces the gallery shows.
 *
 * They are the catalog's own examples — the same files the skills teach from —
 * run through the same compiler the agent's output goes through. Nothing here is
 * hand-written JSON, so a gallery that renders is evidence that the examples
 * compile and the renderer covers them.
 *
 * Output: `src/surfaces.generated.json`, imported by the gallery at build time.
 */

import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { ExpressCompiler } from '../../../packages/express/dist/index.js';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const root = join(here, '..', '..');
const examplesDir = join(root, 'catalogs', 'a2ui-travel', 'examples');

const catalog = JSON.parse(
  readFileSync(join(root, 'catalogs', 'a2ui-travel', 'catalog.json'), 'utf8'),
);
const compiler = new ExpressCompiler(catalog, 'v0.9.1');

/** Which flow each example belongs to, and how to label it. */
const META = {
  '10-inline-flight-options': { flow: 'inline', title: 'Flight options' },
  '20-sidebar-refine': { flow: 'sidebar', title: 'Trip controls' },
  '30-home-dashboard': { flow: 'home', title: 'Trip dashboard' },
  '40-itinerary-day': { flow: 'inline', title: 'Itinerary' },
  '50-traveler-form': { flow: 'inline', title: 'Traveller form' },
};

/** Splits the leading `#` comment lines off an example as its description. */
function splitExample(source) {
  const lines = source.split('\n');
  const comment = [];
  let index = 0;
  while (index < lines.length) {
    const match = /^\s*#\s?(.*)$/.exec(lines[index]);
    if (!match) break;
    comment.push(match[1].trim());
    index += 1;
  }
  return {
    description: comment.filter(Boolean).join(' '),
    body: lines.slice(index).join('\n').trim(),
  };
}

const surfaces = [];

for (const name of readdirSync(examplesDir).filter((file) => file.endsWith('.express')).sort()) {
  const stem = name.replace(/\.express$/, '');
  const meta = META[stem];
  if (!meta) continue; // data-only examples have no surface to show

  const source = readFileSync(join(examplesDir, name), 'utf8');
  const { description, body } = splitExample(source);

  const messages = compiler.compile(source, {
    surfaceId: stem,
    catalogId: catalog.catalogId,
    version: 'v0.9.1',
  });

  // The surface id the Express actually targets, which may differ from the file.
  const created = messages.find((message) => message.createSurface);
  const surfaceId = created?.createSurface.surfaceId ?? stem;

  surfaces.push({
    id: stem,
    surfaceId,
    title: meta.title,
    flow: meta.flow,
    description,
    express: body,
    messages,
    bytes: JSON.stringify(messages).length,
  });
}

if (surfaces.length === 0) {
  console.error('No surfaces compiled — check catalogs/a2ui-travel/examples.');
  process.exit(1);
}

writeFileSync(
  join(here, 'src', 'surfaces.generated.json'),
  `${JSON.stringify(surfaces, null, 2)}\n`,
  'utf8',
);

console.log(
  `Compiled ${surfaces.length} surfaces: ${surfaces.map((surface) => surface.title).join(', ')}`,
);
