// @vitest-environment happy-dom
/**
 * The travel catalog, as the A2UI SDK renders it.
 *
 * This package used to be a renderer and is now a catalog: the SDK's basic
 * components and functions, plus fourteen travel views and two functions of
 * its own. These pin the assembly — that nothing the agent is offered lacks an
 * implementation, and that the basic ones are the SDK's own, not copies.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';
import { basicCatalog } from '@a2ui/web_core/catalogs/basic/v1';

import { calcNights, createTravelCatalog, equals, travelComponentNames } from '../src/index.js';

const document = JSON.parse(
  readFileSync(join(__dirname, '..', '..', '..', 'catalogs', 'a2ui-travel', 'catalog.json'), 'utf8'),
);

describe('the catalog the app renders with', () => {
  const catalog = createTravelCatalog(document);

  it('is the travel catalog, by its own id', () => {
    expect(catalog.id).toBe(document.catalogId);
  });

  it('can draw every component the agent is offered', () => {
    const offered = Object.keys(document.components).sort();
    expect([...catalog.components.keys()].sort()).toEqual(offered);
  });

  it("draws the basic components with the SDK's own implementations", () => {
    for (const name of basicCatalog.components.keys()) {
      if (!(name in document.components)) continue;
      expect(catalog.components.get(name), name).toBe(basicCatalog.components.get(name));
    }
  });

  it('draws the fourteen travel components itself', () => {
    expect(travelComponentNames().sort()).toEqual(
      Object.keys(document.components)
        .filter((name) => !basicCatalog.components.has(name))
        .sort(),
    );
  });

  it('evaluates every function the agent is offered', () => {
    expect([...catalog.functions.keys()].sort()).toEqual(Object.keys(document.functions).sort());
  });

  it('refuses a catalog offering a component nothing here can draw', () => {
    // Offered means in the components *and* in the catalog's `anyComponent`
    // union; `Catalog.fromJson` ignores an entry the union leaves out.
    const union = document.$defs.anyComponent;
    const broken = {
      ...document,
      components: { ...document.components, Teleporter: { type: 'object', properties: { component: { const: 'Teleporter' } } } },
      $defs: {
        ...document.$defs,
        anyComponent: { ...union, oneOf: [...union.oneOf, { $ref: '#/components/Teleporter' }] },
      },
    };
    expect(() => createTravelCatalog(broken)).toThrow(/Teleporter/);
  });
});

describe('calcNights', () => {
  it('counts nights slept, not days spanned', () => {
    expect(calcNights({ start: '2027-04-12', end: '2027-04-15' })).toBe(3);
  });
  it('reads the date and ignores a time or offset', () => {
    expect(calcNights({ start: '2027-04-12T00:00:00Z', end: '2027-04-19' })).toBe(7);
  });
  it('crosses a month and a daylight-saving change', () => {
    expect(calcNights({ start: '2027-03-27', end: '2027-04-02' })).toBe(6);
  });
  it('is zero for a half-filled or inverted range', () => {
    expect(calcNights({ start: '2027-04-12', end: '' })).toBe(0);
    expect(calcNights({ start: '2027-04-19', end: '2027-04-12' })).toBe(0);
  });
});

describe('equals', () => {
  it('marks the row the trip chose', () => {
    expect(equals({ a: 'IB6250', b: 'IB6250' })).toBe(true);
    expect(equals({ a: 'IB6250', b: 'AF242' })).toBe(false);
  });
  it('compares as text, so a numeric id matches its string', () => {
    expect(equals({ a: 7, b: '7' })).toBe(true);
  });
  it('never marks a row when nothing is chosen yet', () => {
    expect(equals({ a: '', b: '' })).toBe(false);
    expect(equals({ a: 'IB6250', b: undefined })).toBe(false);
  });
});
