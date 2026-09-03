/**
 * Store, binding and validation tests.
 *
 * These cover the parts of the host that have to be right for a *streaming*
 * agent: components arriving in several messages, the same component arriving
 * repeatedly as the compile converges, and user edits landing where the next
 * turn will look for them.
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { ExpressCompiler, type CatalogSchema } from '@travel-a2ui/express';

import { evaluateChecks } from '../src/checks.js';
import { callFunction, isSafeUrl } from '../src/functions.js';
import { absolutePointer, resolve, resolveText } from '../src/binding.js';
import { SurfaceStore, readPointer, writePointer } from '../src/store.js';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..', '..');
const catalog = JSON.parse(
  readFileSync(join(root, 'catalogs', 'a2ui-travel', 'catalog.json'), 'utf8'),
) as CatalogSchema;

const compiler = new ExpressCompiler(catalog, 'v0.9.1');
const compile = (source: string, surfaceId = 'test') =>
  compiler.compile(source, { surfaceId, catalogId: catalog.catalogId, version: 'v0.9.1' });

describe('pointers', () => {
  it('reads through objects and arrays', () => {
    const model = { trip: { legs: [{ city: 'Madrid' }, { city: 'Toledo' }] } };
    expect(readPointer(model, '/trip/legs/1/city')).toBe('Toledo');
    expect(readPointer(model, '/trip/nope')).toBeUndefined();
    expect(readPointer(model, '/trip/legs/9/city')).toBeUndefined();
  });

  it('creates an array when the next segment is an index', () => {
    const model: Record<string, never> = {};
    writePointer(model as never, '/packing/0/item', 'Passport');
    writePointer(model as never, '/packing/1/item', 'Adapter');
    expect(model).toEqual({ packing: [{ item: 'Passport' }, { item: 'Adapter' }] });
  });

  it('resolves relative paths against the current list item', () => {
    const scope = { model: {}, itemPointer: '/packing/2' };
    expect(absolutePointer('item', scope)).toBe('/packing/2/item');
    expect(absolutePointer('/trip/city', scope)).toBe('/trip/city');
    expect(absolutePointer('', scope)).toBe('/packing/2');
  });
});

describe('surface store', () => {
  it('applies a compiled surface end to end', () => {
    const store = new SurfaceStore();
    store.apply(compile('$/trip/city = "Madrid"\nt = Text($/trip/city)\nroot = Column([t])'));

    const surface = store.get('test')!;
    expect(surface.components.get('root')).toMatchObject({ component: 'Column' });
    expect(surface.dataModel).toEqual({ trip: { city: 'Madrid' } });
  });

  it('replaces a re-sent component instead of duplicating it', () => {
    const store = new SurfaceStore();
    store.apply(compile('t = Text("First")\nroot = Column([t])'));
    store.apply(compile('t = Text("Second")\nroot = Column([t])'));

    const surface = store.get('test')!;
    expect(surface.components.size).toBe(2);
    expect(surface.components.get('t')).toMatchObject({ text: 'Second' });
  });

  it('merges successive data-model updates rather than replacing them', () => {
    const store = new SurfaceStore();
    store.apply(compile('$/trip/city = "Madrid"\nroot = Text("x")'));
    store.apply(compile('$/filters/maxPrice = 600\nroot = Text("x")'));

    expect(store.get('test')!.dataModel).toEqual({
      trip: { city: 'Madrid' },
      filters: { maxPrice: 600 },
    });
  });

  it('writes user edits to the bound pointer', () => {
    const store = new SurfaceStore();
    store.apply(compile('f = TextField("Name", $/traveler/name)\nroot = Column([f])'));
    store.setValue('test', '/traveler/name', 'Ada');
    expect(store.snapshot('test')).toEqual({ traveler: { name: 'Ada' } });
  });

  it('notifies subscribers once per applied batch', () => {
    const store = new SurfaceStore();
    let calls = 0;
    store.subscribe(() => (calls += 1));
    store.apply(compile('t = Text("x")\nroot = Column([t])'));
    expect(calls).toBe(1);
  });

  it('removes a surface on deleteSurface', () => {
    const store = new SurfaceStore();
    store.apply(compile('root = Text("x")', 'gone'));
    expect(store.has('gone')).toBe(true);
    store.apply(compile('deleteSurface("gone")'));
    expect(store.has('gone')).toBe(false);
  });
});

describe('binding resolution', () => {
  const model = { trip: { city: 'Madrid', total: 2140 }, packing: [{ item: 'Passport' }] };
  const scope = { model, itemPointer: '' };

  it('resolves a literal, a binding, and a dynamic call', () => {
    expect(resolveText('Madrid', scope)).toBe('Madrid');
    expect(resolveText({ path: '/trip/city' }, scope)).toBe('Madrid');
    expect(
      resolve({ call: 'formatCurrency', args: { value: { path: '/trip/total' }, currency: 'EUR' } }, scope),
    ).toContain('2,140');
  });

  it('resolves a relative binding inside a list item', () => {
    expect(resolveText({ path: 'item' }, { model, itemPointer: '/packing/0' })).toBe('Passport');
  });

  it('renders a missing binding as empty rather than "undefined"', () => {
    expect(resolveText({ path: '/nope/nothing' }, scope)).toBe('');
  });
});

describe('checks', () => {
  const scope = { model: { form: { email: 'not-an-email', zip: '1234' } }, itemPointer: '' };

  it('reports the compiled message for a failing rule', () => {
    const messages = compile(
      'f = TextField("Email", $/form/email, ?email("Check that address"))\nroot = Column([f])',
    );
    const components = messages.flatMap((m) =>
      'updateComponents' in m ? m.updateComponents.components : [],
    );
    const field = components.find((c) => c.id === 'f')!;
    const result = evaluateChecks(field['checks'], scope);
    expect(result.ok).toBe(false);
    expect(result.errors).toEqual(['Check that address']);
  });

  it('passes when the bound value satisfies the rule', () => {
    const good = { model: { form: { email: 'ada@example.com' } }, itemPointer: '' };
    const messages = compile('f = TextField("Email", $/form/email, ?email)\nroot = Column([f])');
    const components = messages.flatMap((m) =>
      'updateComponents' in m ? m.updateComponents.components : [],
    );
    expect(evaluateChecks(components.find((c) => c.id === 'f')!['checks'], good).ok).toBe(true);
  });
});

describe('catalog functions', () => {
  it('formats currency, numbers and plurals', () => {
    expect(callFunction('formatCurrency', { value: 1234.5, currency: 'USD' })).toContain('1,234');
    expect(callFunction('formatNumber', { value: 1234567 })).toContain('1,234,567');
    expect(callFunction('pluralize', { count: 1, one: 'night', other: 'nights' })).toBe('night');
    expect(callFunction('pluralize', { count: 3, one: 'night', other: 'nights' })).toBe('nights');
  });

  it('fills a template string', () => {
    expect(
      callFunction('formatString', { template: '{city} in {month}', values: { city: 'Madrid', month: 'April' } }),
    ).toBe('Madrid in April');
  });

  it('never throws on a malformed argument', () => {
    expect(() => callFunction('regex', { value: 'x', pattern: '([' })).not.toThrow();
    expect(callFunction('regex', { value: 'x', pattern: '([' })).toBe(true);
    expect(callFunction('formatDate', { value: 'not a date' })).toBe('not a date');
  });

  it('refuses an unsafe URL scheme', () => {
    expect(isSafeUrl('https://example.com')).toBe(true);
    expect(isSafeUrl('mailto:a@b.co')).toBe(true);
    expect(isSafeUrl('javascript:alert(1)')).toBe(false);
    expect(isSafeUrl('data:text/html,<script>')).toBe(false);
  });
});
