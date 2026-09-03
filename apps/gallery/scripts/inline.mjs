#!/usr/bin/env node
/**
 * Folds the gallery into self-contained HTML.
 *
 * Two outputs, because they go to two places:
 *
 *   dist/gallery.html            a complete document — open it from a file://
 *                                URL, serve it, attach it to an email.
 *   dist/gallery.fragment.html   the same page as body content with a <title>
 *                                and a <style>, for hosts that supply their own
 *                                document skeleton.
 *
 * Everything is inlined either way: no script src, no stylesheet link, no font
 * fetch. A gallery that needs the network to draw is a gallery that shows a
 * blank page in exactly the situations you wanted it for.
 */

import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const dist = join(here, 'dist');

const assets = readdirSync(dist);
const scripts = assets.filter((name) => name.endsWith('.js'));
const styles = assets.filter((name) => name.endsWith('.css'));

if (scripts.length !== 1) {
  console.error(`Expected exactly one JS chunk, found ${scripts.length}: ${scripts.join(', ')}`);
  process.exit(1);
}

const js = readFileSync(join(dist, scripts[0]), 'utf8').replaceAll('</script', '<\\/script');
const css = styles.map((name) => readFileSync(join(dist, name), 'utf8')).join('\n');

const TITLE = 'A2UI surfaces';
const body = `<div id="root"></div>\n<script type="module">${js}</script>`;

writeFileSync(
  join(dist, 'gallery.html'),
  `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>${TITLE}</title>
<style>${css}</style>
</head>
<body>
${body}
</body>
</html>
`,
  'utf8',
);

writeFileSync(
  join(dist, 'gallery.fragment.html'),
  `<title>${TITLE}</title>\n<style>${css}</style>\n${body}\n`,
  'utf8',
);

const kb = (value) => `${(value / 1024).toFixed(1)} kB`;
console.log(`Wrote dist/gallery.html and dist/gallery.fragment.html — ${kb(js.length + css.length)}`);
