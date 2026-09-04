#!/usr/bin/env node
/**
 * Stages the renderer where the Worker serves it from, and guards the names.
 *
 * The bundle has two consumers and neither imports it from `dist/`:
 *
 *   the MCP Apps template — composed by the Worker at request time from these
 *   staged files, so it is always the renderer actually being served and the
 *   Worker never imports a build artifact it cannot be tested without.
 *
 *   `../shell.html` — the older MCP-UI shape, a few hundred bytes with the
 *   payload inlined and a `<script src>` back to this deployment. Source rather
 *   than output, so it is readable in a diff; this script only stages the
 *   bundle it points at.
 *
 * A mismatch between the shell and the built file names is a blank iframe in
 * someone else's app, which is the kind of failure nobody sees until a user
 * reports it — so it is checked here rather than discovered there.
 */

import { copyFileSync, mkdirSync, readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const dist = join(here, 'dist');
const staged = join(here, '..', 'web', 'public', 'mcp-view');

const assets = readdirSync(dist);
const scripts = assets.filter((name) => name.endsWith('.js'));
const styles = assets.filter((name) => name.endsWith('.css'));

if (scripts.length !== 1) {
  console.error(`Expected exactly one JS chunk, found ${scripts.length}: ${scripts.join(', ')}`);
  console.error('Code splitting breaks the single-script shell — check the rollup output options.');
  process.exit(1);
}

const shell = readFileSync(join(here, 'shell.html'), 'utf8');
for (const name of [...scripts, ...styles]) {
  if (!shell.includes(`/mcp-view/${name}`)) {
    console.error(`shell.html does not reference ${name}, so the built bundle would never load.`);
    process.exit(1);
  }
}

mkdirSync(staged, { recursive: true });
for (const name of [...scripts, ...styles]) {
  copyFileSync(join(dist, name), join(staged, name));
}

const kb = (value) => `${(value / 1024).toFixed(1)} kB`;
const bundle = readFileSync(join(dist, scripts[0])).length;
const css = styles.reduce((total, name) => total + readFileSync(join(dist, name)).length, 0);

console.log(
  `Staged the renderer into apps/web/public/mcp-view/ (js ${kb(bundle)}, css ${kb(css)}); ` +
    `shell.html is ${shell.length} B and references both.`,
);
