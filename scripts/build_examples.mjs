#!/usr/bin/env node
/**
 * Compiles the catalog's Express examples and checks in the resulting A2UI JSON.
 *
 * Two things come out of this:
 *
 *  - **Validation.** An example that does not compile is worse than no example:
 *    it teaches the model a mistake, confidently. This fails loudly on one.
 *  - **The `direct_json` skill variant.** Examples are authored once, in
 *    Express, and the JSON form is derived — so the two skill families can
 *    never drift into teaching different UIs.
 *
 * Usage:
 *   node scripts/build_examples.mjs [--check]
 */

import { readFileSync, readdirSync, mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { ExpressCompiler } from '../packages/express/dist/index.js';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const catalogPath = join(root, 'catalogs', 'a2ui-travel', 'catalog.json');
const examplesDir = join(root, 'catalogs', 'a2ui-travel', 'examples');
const compiledDir = join(examplesDir, 'compiled');

const check = process.argv.includes('--check');

const catalog = JSON.parse(readFileSync(catalogPath, 'utf8'));
const compiler = new ExpressCompiler(catalog, 'v0.9.1');

const names = readdirSync(examplesDir)
  .filter((name) => name.endsWith('.express'))
  .sort();

if (names.length === 0) {
  console.error(`No .express examples found in ${examplesDir}`);
  process.exit(1);
}

mkdirSync(compiledDir, { recursive: true });

const stale = [];
const failures = [];

for (const name of names) {
  const stem = name.replace(/\.express$/, '');
  const source = readFileSync(join(examplesDir, name), 'utf8');

  let messages;
  try {
    messages = compiler.compile(source, {
      surfaceId: stem,
      catalogId: catalog.catalogId,
      version: 'v0.9.1',
    });
  } catch (error) {
    failures.push(`${name}: ${error instanceof Error ? error.message : String(error)}`);
    continue;
  }

  const rendered = `${JSON.stringify(messages, null, 2)}\n`;
  const target = join(compiledDir, `${stem}.json`);

  if (check) {
    if (!existsSync(target) || readFileSync(target, 'utf8') !== rendered) stale.push(stem);
  } else {
    writeFileSync(target, rendered, 'utf8');
  }
}

if (failures.length > 0) {
  console.error('Examples that do not compile:\n  ' + failures.join('\n  '));
  process.exit(1);
}

if (check) {
  if (stale.length > 0) {
    console.error(`Stale compiled examples: ${stale.join(', ')}`);
    console.error('Run: node scripts/build_examples.mjs');
    process.exit(1);
  }
  console.log(`All ${names.length} examples compile and their JSON is up to date.`);
} else {
  console.log(`Compiled ${names.length} examples into ${compiledDir.replace(root + '/', '')}.`);
}
