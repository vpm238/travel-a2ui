#!/usr/bin/env node
/**
 * Builds the two shapes the view ships in, for the two kinds of host.
 *
 *   dist/app.html   the whole renderer inlined, no payload. This is the **MCP
 *                   Apps** view: the host reads it once per conversation from
 *                   `ui://travel-a2ui/surface` and each tool result arrives
 *                   afterwards as a `ui/notifications/tool-result` message. So
 *                   inlining costs nothing per call — the objection that
 *                   produced the shell does not apply to a template — and it
 *                   means the sandbox needs no `resourceDomains` at all, which
 *                   is one whole class of CSP failure removed.
 *
 *   ../shell.html   a few hundred bytes with the payload inlined and a
 *                   `<script src>` back to this deployment, used by MCP-UI
 *                   hosts that take a `text/html` resource per tool result.
 *                   Source rather than output, so it is readable in a diff.
 *                   This script only stages the bundle it points at.
 *
 * A mismatch between the shell and the built file names is a blank iframe in
 * someone else's app, which is the kind of failure nobody sees until a user
 * reports it — so it is checked here rather than discovered there.
 */

import { copyFileSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
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

// The MCP Apps view: everything inlined, nothing to fetch, no payload — the
// surface arrives by notification once the host has loaded this.
const js = readFileSync(join(dist, scripts[0]), 'utf8').replaceAll('</script', '<\\/script');
const css = styles.map((name) => readFileSync(join(dist, name), 'utf8')).join('\n');

const app = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>A2UI surface</title>
<style>${css}</style>
</head>
<body>
<div id="root"></div>
<script>${js}</script>
</body>
</html>
`;

writeFileSync(join(dist, 'app.html'), app, 'utf8');

const kb = (value) => `${(value / 1024).toFixed(1)} kB`;

console.log(
  `Wrote dist/app.html (${kb(app.length)}, self-contained) and staged the bundle into ` +
    `apps/web/public/mcp-view/ (js ${kb(js.length)}, css ${kb(css.length)}); ` +
    `shell.html is ${shell.length} B and references both.`,
);
