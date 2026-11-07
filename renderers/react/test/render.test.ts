// @vitest-environment happy-dom
/**
 * What the travel views actually draw, from the catalog's own examples.
 *
 * Every example here is compiled by the A2UI SDK through the server's pipeline
 * and kept current by `npm run check`: the Catalog view's reference
 * (`apps/web/src/generated/catalog-reference.json`, one per component). They
 * are rendered by the real
 * `MessageProcessor` and `A2uiSurface`, and the assertions are about what a
 * traveller would see.
 *
 * And a view may read only what its schema declares: a renderer that reads a
 * property the catalog never offers draws nothing from it, silently.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';
import { A2uiSurface, createComponentImplementation, type ReactCatalogComponent } from '@a2ui/react';
import {
  Catalog,
  MessageProcessor,
  createFunctionImplementation,
  type FunctionImplementation,
} from '@a2ui/web_core/v1_0';
import { basicCatalog } from '@a2ui/web_core/catalogs/basic/v1';

import { createTravelCatalog } from '../src/catalog.js';
import { TRAVEL_VIEWS, type ViewProps } from '../src/components/travel.js';
import { calcNights, equals } from '../src/functions.js';

const ROOT = join(__dirname, '..', '..', '..');
const read = (...path: string[]) => JSON.parse(readFileSync(join(ROOT, ...path), 'utf8'));

const catalogDocument = read('catalogs', 'a2ui-travel', 'catalog.json');
const reference = read('apps', 'web', 'src', 'generated', 'catalog-reference.json') as {
  components: Array<{ name: string; travel: boolean; messages?: unknown[] }>;
};

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** Draws messages with a catalog; the host element and the processor. */
async function draw(messages: unknown[], catalog = createTravelCatalog(catalogDocument)) {
  const processor = new MessageProcessor([catalog], () => undefined);
  processor.processMessages(messages as never);
  const surfaceId = processor.model.surfacesMap.keys().next().value as string;
  const host = window.document.createElement('div');
  window.document.body.appendChild(host);
  await act(async () => {
    createRoot(host).render(createElement(A2uiSurface, { surface: processor.model.getSurface(surfaceId)! }));
  });
  return { host, processor, surfaceId };
}

const example = (name: string) => {
  const found = reference.components.find((entry) => entry.name === name);
  if (!found?.messages) throw new Error(`No reference example for ${name}`);
  return found.messages;
};

/** What each reference example must put on screen. */
const SHOWS: Record<string, string[]> = {
  ActivityItem: ['Prado Museum', '10:00', 'Paseo del Prado 23', '2h', 'Book the timed entry'],
  AirportPicker: ['Where from?', 'JFK'],
  DateRangePicker: ['Trip dates', 'Depart', 'Return', '7 nights'],
  ExpenseSplit: ['Dinner at Sobrino', '€96', 'You', 'Sam'],
  FlightOption: ['Iberia', '18:40', 'JFK', 'MAD', '$412', '7h 35m', 'Nonstop', 'IB6252'],
  GoogleMap: ['Malasaña', 'La Latina'],
  HotelCard: ['Hotel Único Madrid', '$291', 'Salamanca', '9.1 · Superb', 'Breakfast', 'Rooftop'],
  ItineraryDay: ['Day 2 — Old Madrid', 'Prado Museum', 'Lunch at Sobrino'],
  MapPreview: ['Madrid', 'Toledo', 'Day trip, 70km south'],
  PriceSummary: ['Flights', '$824', 'Hotel · 6 nights', '$1,746', '$3,110', '2 travellers'],
  ProgressMeter: ['Spent of budget', '$1,160 left'],
  StatTile: ['Nights in Madrid', '7', '12–19 April'],
  TravelerCounter: ['Travelers', '2', 'Adults on this leg'],
  TripCalendar: ['Fly out', 'Prado'],
  WeatherStrip: ['Mon', '21°', '11°', 'Tue', 'Wed'],
};

describe("each travel component's reference example", () => {
  const travel = reference.components.filter((entry) => entry.travel).map((entry) => entry.name);

  it('has an expectation for every travel component', () => {
    expect(Object.keys(SHOWS).sort()).toEqual([...travel].sort());
  });

  for (const name of Object.keys(SHOWS)) {
    it(`${name} shows what it was given`, async () => {
      const { host } = await draw(example(name));
      const seen = host.textContent ?? '';
      for (const wanted of SHOWS[name]!) expect(seen, `${name}: ${wanted}`).toContain(wanted);
    });
  }

  it('the progress meter fills to its value over its max', async () => {
    const { host } = await draw(example('ProgressMeter'));
    const bar = host.querySelector('[role="progressbar"]')!;
    expect(bar.getAttribute('aria-valuenow')).toBe('1840');
    expect(bar.getAttribute('aria-valuemax')).toBe('3000');
    expect(bar.getAttribute('aria-label')).toBe('Spent of budget');
    expect((host.querySelector('.tv-meter__fill') as HTMLElement).style.width).toBe('61.33333333333333%');
  });

  it("the stepper's buttons say what they count", async () => {
    const { host } = await draw(example('TravelerCounter'));
    const labels = [...host.querySelectorAll('.tv-stepper button')].map((button) =>
      button.getAttribute('aria-label'),
    );
    expect(labels).toEqual(['One fewer: Travelers', 'One more: Travelers']);
  });

  it("an activity's controls are siblings, never nested", async () => {
    const { host } = await draw(example('ActivityItem'));
    expect(host.querySelector('button button, [role="button"] button')).toBeNull();
  });
});

describe('a chosen card', () => {
  // A fare bound the way the Flights macro binds it: chosen when its id is the
  // one recorded at /trip/selectedFlight. (A whole list is drawn in a real
  // browser by tools/e2e/chat.mjs: the SDK's basic List and Column are web
  // components that this DOM does not render.)
  const fare = (surfaceId: string) => [
    {
      version: '1.0',
      createSurface: {
        surfaceId,
        catalogId: catalogDocument.catalogId,
        components: [
          {
            id: 'root',
            component: 'FlightOption',
            airline: 'Iberia',
            departTime: '18:40',
            arriveTime: '08:15 +1',
            origin: 'JFK',
            destination: 'MAD',
            price: '$412',
            action: { event: { name: 'select_flight', context: { id: 'IB6252' } } },
            selected: { '@call': 'equals', args: { a: 'IB6252', b: { '@path': '/trip/selectedFlight' } } },
          },
        ],
      },
    },
  ];

  it('says so, for the eye and for a screen reader, once it is the one on the record', async () => {
    const { host, processor, surfaceId } = await draw(fare('chosen-1'));
    const card = () => host.querySelector('.tv-fare')!;
    expect(card().getAttribute('aria-pressed')).toBe('false');
    expect(card().classList.contains('is-selected')).toBe(false);
    await act(async () => {
      processor.processMessages([
        { version: '1.0', updateDataModel: { surfaceId, path: '/trip/selectedFlight', value: 'IB6252' } },
      ] as never);
    });
    expect(card().getAttribute('aria-pressed')).toBe('true');
    expect(card().classList.contains('is-selected')).toBe(true);
  });
});

describe('a view reads only what its schema declares', () => {
  /** The travel catalog with every view watched: what each one read, by name. */
  function watchedCatalog(reads: Map<string, Set<string>>) {
    const schemas = Catalog.fromJson(catalogDocument);
    const components: ReactCatalogComponent[] = [...schemas.components.entries()].map(([name, api]) => {
      const fromSdk = basicCatalog.components.get(name);
      if (fromSdk) return fromSdk;
      const view = TRAVEL_VIEWS[name]!;
      const seen = reads.get(name) ?? new Set<string>();
      reads.set(name, seen);
      const watched = (given: ViewProps) =>
        view({
          ...given,
          props: new Proxy(given.props, {
            get(target, key) {
              if (typeof key === 'string') seen.add(key);
              return target[key as string];
            },
          }),
        });
      return createComponentImplementation(api, watched);
    });
    const own: Record<string, (args: Record<string, unknown>) => unknown> = { calcNights, equals };
    const functions: FunctionImplementation[] = [...schemas.functions.entries()].map(
      ([name, api]) =>
        basicCatalog.functions.get(name) ?? createFunctionImplementation(api, (args) => own[name]!(args)),
    );
    return (schemas as never as Catalog<ReactCatalogComponent, FunctionImplementation>).withEntries(
      components,
      functions,
    );
  }

  /** What the binder may hand a view: the declared props, a setter per bindable one, and check results. */
  function allowed(name: string): Set<string> {
    const api = Catalog.fromJson(catalogDocument).components.get(name)! as unknown as {
      schema: { shape?: Record<string, unknown>; _def?: { shape?: () => Record<string, unknown> } };
    };
    const shape = api.schema.shape ?? api.schema._def?.shape?.() ?? {};
    const declared = Object.keys(shape);
    const setters = declared.map((key) => `set${key[0]!.toUpperCase()}${key.slice(1)}`);
    return new Set([...declared, ...setters, 'isValid', 'validationErrors']);
  }

  it('holds for every travel component in its reference example', async () => {
    const reads = new Map<string, Set<string>>();
    const catalog = watchedCatalog(reads);
    for (const name of Object.keys(SHOWS)) await draw(example(name), catalog);
    const strays = [...reads].flatMap(([name, keys]) =>
      [...keys].filter((key) => !allowed(name).has(key)).map((key) => `${name}.${key}`),
    );
    expect(strays).toEqual([]);
    expect(reads.get('FlightOption')?.size).toBeGreaterThan(0);
  });
});
