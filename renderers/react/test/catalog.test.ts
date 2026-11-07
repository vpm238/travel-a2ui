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

describe('the travel views read the catalog', () => {
  // Every property a view reads must be one its catalog entry declares, or an
  // item property of one of its arrays (a writable property's `setX` setter is
  // the SDK's). A view reading a name the catalog never mentions draws nothing
  // for a field the agent filled in.
  it('reads only properties its catalog entry declares', () => {
    const source = readFileSync(join(__dirname, '..', 'src', 'components', 'travel.tsx'), 'utf8');
    const common = new Set(['weight', 'accessibility', 'id', 'checks', 'validationErrors', 'component']);
    const problems: string[] = [];
    let scanned = 0;
    for (const match of source.matchAll(/export function (\w+)\(\{[^)]*\}: ViewProps\) \{/g)) {
      const component = match[1]!;
      const schema = document.components[component];
      if (!schema) continue;
      scanned += 1;
      const rest = source.slice(match.index! + match[0].length);
      const end = rest.search(/\nexport function |\n\/\/ -{4,}/);
      const body = end === -1 ? rest : rest.slice(0, end);

      const declared = new Set<string>();
      const items = new Set<string>();
      for (const part of schema.allOf ?? [schema]) {
        for (const [key, value] of Object.entries<Record<string, any>>(part.properties ?? {})) {
          declared.add(key);
          for (const item of Object.keys(value.items?.properties ?? {})) items.add(item);
        }
      }
      const isSetter = (key: string) => /^set[A-Z]/.test(key) && declared.has(key[3]!.toLowerCase() + key.slice(4));
      const top = [...body.matchAll(/props\['(\w+)'\]/g)].map((m) => m[1]!);
      const itemReads = [...body.matchAll(/\b(\w+)\['(\w+)'\]/g)].filter((m) => m[1] !== 'props').map((m) => m[2]!);
      const undeclared = top.filter((key) => !declared.has(key) && !common.has(key) && !isSetter(key));
      const undeclaredItems = itemReads.filter((key) => !items.has(key) && !declared.has(key));
      if (undeclared.length || undeclaredItems.length) {
        problems.push(`${component} reads ${[...new Set(undeclared)]} (items ${[...new Set(undeclaredItems)]})`);
      }
    }
    expect(scanned).toBe(Object.keys(document.components).length - basicCatalog.components.size);
    expect(problems).toEqual([]);
  });
});
