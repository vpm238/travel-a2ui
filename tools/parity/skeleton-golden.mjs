#!/usr/bin/env node
/**
 * Dumps the skeleton surfaces, which is really a test of the two compilers.
 *
 * The skeleton is a fixed Express program compiled to A2UI — bindings, a
 * `_template` row, an `Event` with bound context. Both implementations compile
 * it: the TypeScript through this repo's Express port, the Python through the
 * SDK's `ExpressParser`, which is the reference implementation. If those two
 * disagree about what this program means, the whole premise of the project is
 * wrong, and it would be wrong quietly — the surface would still render, just
 * differently.
 *
 * They agree, on everything except one field. See the note on `catalogId` in
 * the Python test that reads this.
 *
 *   node tools/parity/skeleton-golden.mjs            # write
 *   node tools/parity/skeleton-golden.mjs --check    # fail if it moved
 */

import { execFileSync } from 'node:child_process';
import { mkdirSync, existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');
const OUT = join(here, '__golden__', 'skeleton.json');

const cache = join(root, 'node_modules', '.cache');
const entry = join(cache, 'skeleton-golden-entry.ts');
const bundle = join(cache, 'skeleton-golden.mjs');
mkdirSync(cache, { recursive: true });
writeFileSync(
  entry,
  [
    "import { ExpressCompiler } from '@travel-a2ui/express';",
    "import CATALOG from '../../catalogs/a2ui-travel/catalog.json';",
    "import { pendingSurfaceFor } from '../../apps/worker/src/skeleton.js';",
    'export function openings() {',
    "  const compiler = new ExpressCompiler(CATALOG as never, 'v0.9.1');",
    '  const out: Record<string, unknown> = {};',
    "  for (const tool of ['search_flights', 'search_hotels', 'estimate_cost']) {",
    "    const pending = pendingSurfaceFor(tool, 'inline-1', compiler, String(CATALOG.catalogId), 'v0.9.1');",
    '    out[tool] = pending ? { opening: pending.opening, filled: filledFor(tool, pending) } : null;',
    '  }',
    '  return out;',
    '}',
    'function filledFor(tool: string, pending: { fill(result: unknown): unknown }) {',
    '  const rows = [{ id: "a", airline: "Iberia", price: "$257", name: "Hotel One" }];',
    "  const key = tool === 'search_flights' ? 'flights' : 'hotels';",
    '  return {',
    '    withRows: pending.fill({ [key]: rows }),',
    '    withNothing: pending.fill({ [key]: [] }),',
    '    withGarbage: pending.fill(null),',
    '  };',
    '}',
  ].join('\n'),
);
execFileSync(
  join(root, 'node_modules', '.bin', 'esbuild'),
  [
    entry,
    '--bundle',
    '--format=esm',
    '--platform=node',
    `--outfile=${bundle}`,
    '--alias:@travel-a2ui/express=./packages/express/src/index.ts',
    '--log-level=warning',
  ],
  { cwd: root, stdio: 'inherit' },
);
const { openings } = await import(`file://${bundle}`);

const text = `${JSON.stringify(openings(), null, 2)}\n`;

if (process.argv.includes('--check')) {
  if (!existsSync(OUT)) {
    console.error(`Missing ${OUT}. Run: node tools/parity/skeleton-golden.mjs`);
    process.exit(1);
  }
  if (readFileSync(OUT, 'utf-8') !== text) {
    console.error('The skeleton golden moved. Run: node tools/parity/skeleton-golden.mjs');
    process.exit(1);
  }
  console.log('skeleton golden: unchanged');
} else {
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, text);
  console.log(`Wrote ${OUT}`);
}

rmSync(bundle, { force: true });
rmSync(entry, { force: true });
