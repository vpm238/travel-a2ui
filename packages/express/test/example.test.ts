/**
 * Every component in the catalog has a preview that compiles.
 *
 * The gallery renders these for real, so a component whose generated example
 * does not compile is a component that shows an error where it should show
 * itself. Deriving them from the schema means a new component gets a preview
 * for free — and means this test is what notices when a schema change breaks
 * the derivation.
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { ExpressCompiler, exampleExpress } from '../src/index.js';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const catalog = JSON.parse(
  readFileSync(join(root, 'catalogs', 'a2ui-travel', 'catalog.json'), 'utf8'),
);
const compiler = new ExpressCompiler(catalog, 'v0.9.1');
const names: string[] = Object.keys(catalog.components);

describe('component previews', () => {
  it('covers the whole catalog', () => {
    expect(names.length).toBeGreaterThan(20);
    for (const name of names) {
      expect(exampleExpress(catalog, name), `${name} has no example`).toBeTruthy();
    }
  });

  it.each(names)('%s compiles and draws itself', (name) => {
    const source = exampleExpress(catalog, name)!;
    const messages = compiler.compile(source, {
      surfaceId: 'preview',
      catalogId: String(catalog.catalogId),
      version: 'v0.9.1',
    });

    const components = messages.flatMap((message: any) =>
      message.updateComponents?.components ?? message.createSurface?.components ?? [],
    );
    // The component being previewed is actually in the output, rather than the
    // example happening to compile into something else entirely.
    expect(components.some((node: any) => node.component === name)).toBe(true);
  });

  it('returns null for a component the catalog does not have', () => {
    expect(exampleExpress(catalog, 'NoSuchComponent')).toBeNull();
  });

  it('names arguments once it has skipped one', () => {
    // Positional arguments are matched by position, so an optional one left out
    // shifts everything after it. Button is the shape that catches this.
    const source = exampleExpress(catalog, 'Button')!;
    expect(() =>
      compiler.compile(source, {
        surfaceId: 'preview',
        catalogId: String(catalog.catalogId),
        version: 'v0.9.1',
      }),
    ).not.toThrow();
  });
});
