/**
 * `formatString` templates, as the spec defines them.
 *
 * Every case here is written against the catalog's own description of the
 * function, not against what the implementation happened to do — because what
 * the implementation happened to do was `{name}` substitution against a
 * `values` object, and a spec-correct template came back verbatim. A live run
 * printed `${calcNights(start: ${/trip/startDate}, …)} nights` on screen.
 */

import { describe, expect, it } from 'vitest';

import { interpolate } from '../src/interpolate.js';
import { callFunction } from '../src/functions.js';
import { itemsAt } from '../src/Surface.js';

const model = {
  trip: { startDate: '2027-04-12', endDate: '2027-04-19', total: 1240, city: 'Madrid' },
};

const lookup = {
  readPath: (path: string) =>
    path
      .split('/')
      .filter(Boolean)
      .reduce<any>((node, key) => (node == null ? undefined : node[key]), model),
  call: callFunction,
};

const run = (template: string) => interpolate(template, lookup);

describe('paths', () => {
  it('reads an absolute pointer', () => {
    expect(run('Flying to ${/trip/city}')).toBe('Flying to Madrid');
  });

  it('leaves the text around an expression alone', () => {
    expect(run('${/trip/city}, in April')).toBe('Madrid, in April');
  });

  it('resolves several in one template', () => {
    expect(run('${/trip/startDate} to ${/trip/endDate}')).toBe('2027-04-12 to 2027-04-19');
  });

  it('renders a missing path as nothing rather than the source', () => {
    expect(run('[${/trip/nope}]')).toBe('[]');
  });
});

describe('function calls', () => {
  /** The exact label the live run failed to render. */
  it('resolves a call whose arguments are themselves expressions', () => {
    expect(run('${calcNights(start: ${/trip/startDate}, end: ${/trip/endDate})} nights')).toBe(
      '7 nights',
    );
  });

  it('takes a quoted literal argument', () => {
    expect(run("${formatCurrency(value: ${/trip/total}, currency: 'EUR')}")).toContain('1,240');
  });

  it('nests a call inside a call', () => {
    expect(
      run(
        '${pluralize(value: ${calcNights(start: ${/trip/startDate}, end: ${/trip/endDate})}, ' +
          "one: 'one night', other: 'a week')}",
      ),
    ).toBe('a week');
  });

  it('handles a comma inside a quoted argument', () => {
    expect(run("${formatString(value: 'Madrid, Spain')}")).toBe('Madrid, Spain');
  });
});

describe('degrading', () => {
  it('escapes a literal dollar-brace', () => {
    expect(run('\\${not an expression}')).toBe('${not an expression}');
  });

  /** A model mid-stream, with the closing brace not yet sent. */
  it('emits an unclosed expression as text instead of swallowing the rest', () => {
    expect(run('cost ${formatCurrency(value: 12')).toBe('cost ${formatCurrency(value: 12');
  });

  it('passes a template with no expressions straight through', () => {
    expect(run('7 nights')).toBe('7 nights');
  });

  it('is empty for an empty expression', () => {
    expect(run('${}')).toBe('');
  });
});

/**
 * Which shapes a `_template` repeats over.
 *
 * Exercised through the exported helper rather than through React, because the
 * question is arithmetic — what counts as a list — and not rendering.
 */
describe('template indices', () => {
  it('repeats over an array', () => {
    expect(itemsAt([{ a: 1 }, { a: 2 }, { a: 3 }])).toEqual([0, 1, 2]);
  });

  /** What the reference compiler actually produces for `$/items/0/…`. */
  it('repeats over a map keyed 0..n-1', () => {
    expect(itemsAt({ '0': {}, '1': {} })).toEqual([0, 1]);
  });

  it('refuses a map with gaps, which would invent rows', () => {
    expect(itemsAt({ '0': {}, '2': {} })).toEqual([]);
  });

  it('refuses an ordinary object that happens to contain a "0"', () => {
    expect(itemsAt({ '0': {}, label: 'x' })).toEqual([]);
  });

  it('is empty for nothing at all', () => {
    expect(itemsAt(undefined)).toEqual([]);
    expect(itemsAt([])).toEqual([]);
    expect(itemsAt({})).toEqual([]);
  });
});
