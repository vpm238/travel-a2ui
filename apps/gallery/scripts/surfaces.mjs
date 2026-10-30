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

import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { ExpressCompiler, exampleExpress } from '../../../packages/express/dist/index.js';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const root = join(here, '..', '..');
const examplesDir = join(root, 'catalogs', 'a2ui-travel', 'examples');

const catalog = JSON.parse(
  readFileSync(join(root, 'catalogs', 'a2ui-travel', 'catalog.json'), 'utf8'),
);
/**
 * The protocol the catalog declares — not a literal.
 *
 * This said `'v0.9.1'` in three places while the app spoke 1.0, and the gallery
 * went on looking right, because the renderer reads both spellings of a binding
 * on purpose. What it was proving is that the renderer still handles 0.9. The
 * gallery is the page people are shown to see what the host draws, so it should
 * be drawing what production sends.
 */
const VERSION = `v${catalog.protocolVersion ?? '0.9'}`;

const compiler = new ExpressCompiler(catalog, VERSION);

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

  // The messages `build_examples.py` already compiled, not a second compile
  // here.
  //
  // This re-ran the TypeScript compiler over the same Express, which worked
  // right up to the first example that used a macro: `Flights()` is in the
  // catalog the *model* is given, expanded host-side on the way out, and this
  // compiler has no expander — "'Flights' is not a component in this catalog".
  //
  // Reading the compiled JSON is also simply more honest. It is what the brief
  // teaches from and what the server would send; a parallel compile here could
  // agree with it or not, and nothing would have said which.
  const compiledPath = join(examplesDir, 'compiled', `${stem}.json`);
  if (!existsSync(compiledPath)) {
    console.error(`${stem}: no compiled JSON — run scripts/build_examples.py first.`);
    process.exitCode = 1;
    continue;
  }
  const messages = JSON.parse(readFileSync(compiledPath, 'utf8'));

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

/**
 * One surface per component, so the gallery is a component gallery too.
 *
 * The flows above show components in context, which is the right way to judge
 * whether the *app* works and the wrong way to find out what a `ProgressMeter`
 * looks like. These are derived from each component's own schema, so a
 * component added to the catalog turns up here on the next build with nothing
 * written by hand.
 */
const components = [];

for (const name of Object.keys(catalog.components).sort()) {
  const express = exampleExpress(catalog, name);
  if (!express) continue;

  const surfaceId = `component-${name}`;
  let messages;
  try {
    messages = compiler.compile(express, {
      surfaceId,
      catalogId: catalog.catalogId,
      version: VERSION,
    });
  } catch (error) {
    // A preview that will not compile is a real problem with the catalog or the
    // derivation, and a gallery quietly missing a component hides it.
    console.error(`${name}: ${error.message}`);
    process.exit(1);
  }

  components.push({
    id: surfaceId,
    surfaceId,
    name,
    description: catalog.components[name]?.description ?? '',
    express,
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

writeFileSync(
  join(here, 'src', 'components.generated.json'),
  `${JSON.stringify(components, null, 2)}\n`,
  'utf8',
);

console.log(
  `Compiled ${surfaces.length} surfaces (${surfaces.map((surface) => surface.title).join(', ')}) ` +
    `and ${components.length} component previews.`,
);
