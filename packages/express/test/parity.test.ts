/**
 * Parity against the reference implementation.
 *
 * Every `.express` case is compiled here by the TypeScript compiler and
 * compared against a golden produced by Google's Python compiler
 * (`scripts/gen_parity.py`). A port that "looks right" is worth very little;
 * this is the test that says it *is* right.
 *
 * When a case fails, the golden is the authority. Fix the port.
 */

import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { ExpressCompiler } from '../src/compiler.js';
import { ExpressDecompiler } from '../src/decompiler.js';
import type { CatalogSchema } from '../src/types.js';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..', '..');
const casesDir = join(root, 'tools', 'parity', 'cases');
const expectedDir = join(root, 'tools', 'parity', 'expected');

const catalog = JSON.parse(
  readFileSync(join(root, 'catalogs', 'a2ui-travel', 'catalog.json'), 'utf8'),
) as CatalogSchema;

const SURFACE_ID = 'parity-surface';
const compiler = new ExpressCompiler(catalog, 'v0.9.1');
const decompiler = new ExpressDecompiler(catalog);

const cases = readdirSync(casesDir)
  .filter((name) => name.endsWith('.express'))
  .sort();

describe('parity with the reference A2UI Express compiler', () => {
  it('has cases to run', () => {
    expect(cases.length).toBeGreaterThan(0);
  });

  for (const name of cases) {
    const stem = name.replace(/\.express$/, '');

    it(`compiles ${stem} identically`, () => {
      const source = readFileSync(join(casesDir, name), 'utf8');
      const golden = JSON.parse(readFileSync(join(expectedDir, `${stem}.json`), 'utf8'));

      const actual = compiler.compile(source, {
        surfaceId: SURFACE_ID,
        catalogId: catalog.catalogId,
        version: 'v0.9.1',
      });

      expect(actual).toEqual(golden);
    });
  }
});

describe('round-tripping through the decompiler', () => {
  for (const name of cases) {
    const stem = name.replace(/\.express$/, '');

    it(`survives compile → decompile → compile for ${stem}`, () => {
      const source = readFileSync(join(casesDir, name), 'utf8');
      const first = compiler.compile(source, {
        surfaceId: SURFACE_ID,
        catalogId: catalog.catalogId,
        version: 'v0.9.1',
      });

      const express = decompiler.decompile(first as never);
      const second = compiler.compile(express, {
        surfaceId: SURFACE_ID,
        catalogId: catalog.catalogId,
        version: 'v0.9.1',
      });

      expect(second).toEqual(first);
    });
  }
});
