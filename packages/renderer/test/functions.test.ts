/**
 * Every function the catalog promises.
 *
 * This file exists because of a bug that never threw anything. `formatString`
 * is specified to interpolate `${…}` expressions against the data model; what
 * was implemented did `{name}` substitution against a `values` object — a
 * different function wearing the same name. A spec-correct template came back
 * untouched and the page printed it as source. Nothing failed, it just
 * displayed, and 284 tests agreed with the implementation because they had been
 * written from the implementation.
 *
 * So the first test here is structural: it walks `catalog.json` and fails if a
 * function is declared and not implemented. The rest read the catalog's own
 * descriptions of what each one does, not the code's.
 */

import { describe, expect, it } from 'vitest';

import { callFunction, isSafeUrl } from '../src/functions.js';
import { interpolate } from '../src/interpolate.js';
import catalog from '../../../catalogs/a2ui-travel/catalog.json';

const DECLARED = Object.keys((catalog as { functions: Record<string, unknown> }).functions);

/** The arguments each function's schema marks required. */
function requiredArgs(name: string): string[] {
  const fn = (catalog as any).functions[name];
  return fn?.properties?.args?.required ?? [];
}

describe('the catalog contract', () => {
  it('declares functions this renderer knows about', () => {
    expect(DECLARED.length).toBeGreaterThan(10);
  });

  /**
   * A declared function with no implementation returns `undefined` here, which
   * on a surface is a silently blank label.
   */
  it.each(DECLARED)('implements %s', (name) => {
    const args: Record<string, unknown> = {};
    for (const key of requiredArgs(name)) {
      args[key] = key === 'values' ? [true] : key === 'pattern' ? '.*' : '1';
    }
    expect(callFunction(name, args as never)).toBeDefined();
  });

  it.each(DECLARED)('never throws on rubbish arguments: %s', (name) => {
    expect(() => callFunction(name, { value: { nested: [1] }, values: 'not a list' } as never))
      .not.toThrow();
  });
});

describe('formatting', () => {
  it('formats a currency with its symbol and grouping', () => {
    const out = String(callFunction('formatCurrency', { value: 1240, currency: 'EUR' } as never));
    expect(out).toMatch(/1[.,  ]?240/);
    expect(out).toMatch(/€|EUR/);
  });

  it('honours an explicit decimal count', () => {
    expect(String(callFunction('formatCurrency', { value: 12, currency: 'USD', decimals: 0 } as never)))
      .not.toContain('.00');
  });

  it('can be told not to group', () => {
    expect(String(callFunction('formatNumber', { value: 12000, grouping: false } as never)))
      .toBe('12000');
  });

  it('returns the input unchanged when it is not a number', () => {
    expect(callFunction('formatNumber', { value: 'soon' } as never)).toBe('soon');
  });

  it('formats a date, and leaves an unparseable one alone', () => {
    expect(String(callFunction('formatDate', { value: '2027-04-12', format: 'short' } as never)))
      .toMatch(/Apr/);
    expect(callFunction('formatDate', { value: 'whenever', format: 'short' } as never))
      .toBe('whenever');
  });

  /** The spec's own shape: a template of `${…}` expressions, not `{name}`. */
  it('interpolates a formatString template', () => {
    expect(
      interpolate('${/city} in ${/month}', {
        readPath: (p) => ({ '/city': 'Madrid', '/month': 'April' })[p],
        call: callFunction,
      }),
    ).toBe('Madrid in April');
  });
});

describe('travel arithmetic', () => {
  /** The 12th to the 15th is three nights, not four days. */
  it('counts nights the way a hotel counts them', () => {
    expect(callFunction('calcNights', { start: '2027-04-12', end: '2027-04-15' } as never)).toBe(3);
  });

  it('is zero for a range that runs backwards, rather than negative', () => {
    expect(callFunction('calcNights', { start: '2027-04-15', end: '2027-04-12' } as never)).toBe(0);
  });

  it('is zero when a date is missing, so a half-filled form shows nothing odd', () => {
    expect(callFunction('calcNights', { start: '2027-04-12' } as never)).toBe(0);
  });

  it('picks a plural form by count', () => {
    const args = { one: '1 night', other: 'several nights' };
    expect(callFunction('pluralize', { value: 1, ...args } as never)).toBe('1 night');
    expect(callFunction('pluralize', { value: 7, ...args } as never)).toBe('several nights');
  });

  it('falls back to `other` when the count has no matching form', () => {
    expect(callFunction('pluralize', { value: 0, other: 'no nights' } as never)).toBe('no nights');
  });
});

describe('checks', () => {
  it('required is false only for genuinely empty values', () => {
    expect(callFunction('required', { value: 'JFK' } as never)).toBe(true);
    expect(callFunction('required', { value: '' } as never)).toBe(false);
    expect(callFunction('required', { value: 0 } as never)).toBe(false);
  });

  it('regex matches, and passes an unparseable pattern rather than failing a good field', () => {
    expect(callFunction('regex', { value: 'MAD', pattern: '^[A-Z]{3}$' } as never)).toBe(true);
    expect(callFunction('regex', { value: 'Madrid', pattern: '^[A-Z]{3}$' } as never)).toBe(false);
    expect(callFunction('regex', { value: 'anything', pattern: '([' } as never)).toBe(true);
  });

  it('length and numeric bound their values', () => {
    expect(callFunction('length', { value: 'MAD', min: 3, max: 3 } as never)).toBe(true);
    expect(callFunction('length', { value: 'MA', min: 3 } as never)).toBe(false);
    expect(callFunction('numeric', { value: 2, min: 1, max: 9 } as never)).toBe(true);
    expect(callFunction('numeric', { value: 0, min: 1 } as never)).toBe(false);
    expect(callFunction('numeric', { value: 'four' } as never)).toBe(false);
  });

  it('email accepts an address and rejects a sentence', () => {
    expect(callFunction('email', { value: 'a@b.co' } as never)).toBe(true);
    expect(callFunction('email', { value: 'not an email' } as never)).toBe(false);
  });

  it('combines checks with and / or / not', () => {
    expect(callFunction('and', { values: [true, true] } as never)).toBe(true);
    expect(callFunction('and', { values: [true, false] } as never)).toBe(false);
    expect(callFunction('or', { values: [false, true] } as never)).toBe(true);
    expect(callFunction('or', { values: [false, false] } as never)).toBe(false);
    expect(callFunction('not', { value: false } as never)).toBe(true);
  });
});

describe('openUrl', () => {
  /**
   * The one function that reaches outside the page, so the one that has to
   * refuse. A catalog function's arguments are model-controlled input, and
   * `javascript:` in an href is a script injection with extra steps.
   */
  it('allows the schemes a link may legitimately use', () => {
    for (const url of ['https://a.example', 'http://a.example', 'mailto:a@b.co', '/local', '#here'])
      expect(isSafeUrl(url)).toBe(true);
  });

  it('refuses everything else', () => {
    for (const url of ['javascript:alert(1)', 'data:text/html,<script>', 'file:///etc/passwd', ''])
      expect(isSafeUrl(url)).toBe(false);
  });
});
