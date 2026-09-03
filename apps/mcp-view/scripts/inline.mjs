#!/usr/bin/env node
/**
 * Emits the MCP view's shell and stages its bundle for the Worker to serve.
 *
 * A tool result carries an HTML resource the host renders in an iframe. That
 * resource is a **shell**: a few hundred bytes with the surface inlined and a
 * `<script src>` pointing at this deployment. The renderer itself — React and
 * the component library, about 230 kB — is served once from the origin and
 * cached, instead of riding along on every tool call.
 *
 * The payload stays inlined even so. It is small, it is the only part that
 * varies, and inlining it means the surface has everything it needs the moment
 * the script boots — no second round trip, no loading state.
 *
 * Two outputs:
 *   dist/shell.html          the template, imported by the Worker as text
 *   ../web/public/mcp-view/  the bundle, picked up by the web app's build and
 *                            served from the same origin as everything else
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

mkdirSync(staged, { recursive: true });
for (const name of [...scripts, ...styles]) {
  copyFileSync(join(dist, name), join(staged, name));
}

/**
 * `__ORIGIN__` is filled in per request from the URL the host called, so a
 * deployment, a preview and `wrangler dev` each serve their own bundle without
 * anything being configured.
 */
const shell = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>A2UI surface</title>
<link rel="stylesheet" href="__ORIGIN__/mcp-view/app.css">
</head>
<body>
<script id="a2ui-payload" type="application/json">__A2UI_PAYLOAD__</script>
<div id="root"></div>
<script src="__ORIGIN__/mcp-view/app.js" defer></script>
</body>
</html>
`;

writeFileSync(join(dist, 'shell.html'), shell, 'utf8');

const kb = (value) => `${(value / 1024).toFixed(1)} kB`;
const bundle = readFileSync(join(dist, scripts[0])).length;
const css = styles.reduce((total, name) => total + readFileSync(join(dist, name)).length, 0);

console.log(
  `Wrote dist/shell.html (${shell.length} B) and staged the bundle ` +
    `(js ${kb(bundle)}, css ${kb(css)}) into apps/web/public/mcp-view/`,
);
