#!/usr/bin/env node
/**
 * Stages the MCP view's bundle where the Worker can serve it, and checks that
 * the shell still points at what was built.
 *
 * A tool result carries an HTML resource the host renders in an iframe. That
 * resource is `../shell.html` — a few hundred bytes with the surface inlined
 * and a `<script src>` pointing at this deployment. The renderer itself, React
 * and the component library, is served once from the origin and cached instead
 * of riding along on every tool call.
 *
 * The shell is **source**, not output: nothing about it depends on the build,
 * so it is checked in, imported by the Worker directly, and readable in a diff.
 * This script only moves the bundle and guards the two file names they agree on
 * — a mismatch here is a blank iframe in someone else's app, which is exactly
 * the kind of failure nobody sees until a user reports it.
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
