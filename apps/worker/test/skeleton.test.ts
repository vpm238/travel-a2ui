/**
 * Drawing the interface before the data exists.
 *
 * What is asserted here is an *order*, because the order is the whole feature:
 * the layout has to be on screen while the search is still running, not after.
 * A test that only checked the final surface would pass just as happily against
 * the behaviour this replaced, where nothing appeared until everything had.
 */

import { describe, expect, it } from 'vitest';
import { ExpressCompiler } from '@travel-a2ui/express';

import { CATALOG, CATALOG_ID } from '../src/agent.js';
import { pendingSurfaceFor } from '../src/skeleton.js';
import { providerFor } from '../src/providers/index.js';

const compiler = new ExpressCompiler(CATALOG, 'v0.9.1');
const pending = (tool: string) =>
  pendingSurfaceFor(tool, 'inline-1', compiler, CATALOG_ID, 'v0.9.1');

const opsOf = (messages: any[]) =>
  messages.map((message) => Object.keys(message).find((key) => key !== 'version'));

describe('the opening', () => {
  it('creates the surface, seeds it blank, then paints', () => {
    // The seed has to land before the components: a `_template` painting
    // against a data model that does not exist yet repeats over nothing.
    expect(opsOf(pending('search_flights')!.opening)).toEqual([
      'createSurface',
      'updateDataModel',
      'updateComponents',
    ]);
  });

  it('lays out as many blank rows as the search will return', () => {
    const seed = pending('search_flights')!.opening[1] as any;
    expect(seed.updateDataModel.path).toBe('/flights');
    expect(seed.updateDataModel.value).toEqual([{}, {}, {}, {}]);
  });

  /**
   * Blank rather than empty-stringed, and the difference is the visible one:
   * an unresolved path renders as pending, a path holding `''` renders as
   * nothing at all. Seeding `{ price: '' }` would lay out four silent cards.
   */
  it('seeds rows that exist and hold nothing', () => {
    const seed = pending('search_flights')!.opening[1] as any;
    for (const row of seed.updateDataModel.value) {
      expect(Object.keys(row)).toHaveLength(0);
    }
  });

  it('binds every field it will later fill', () => {
    const components = (pending('search_flights')!.opening[2] as any).updateComponents.components;
    const row = components.find((c: any) => c.component === 'FlightOption');

    for (const field of ['airline', 'departTime', 'arriveTime', 'origin', 'destination', 'price']) {
      expect(row[field], field).toHaveProperty('path');
    }
  });

  /**
   * `cabin` is a plain enum in the catalog rather than a bindable common type,
   * so it cannot be filled later and is left off rather than bound and broken.
   */
  it('leaves out what the catalog will not let it bind', () => {
    const components = (pending('search_flights')!.opening[2] as any).updateComponents.components;
    const row = components.find((c: any) => c.component === 'FlightOption');
    expect(row).not.toHaveProperty('cabin');
  });

  it('has nothing to draw for a tool whose answer has no fixed shape', () => {
    expect(pending('estimate_cost')).toBeUndefined();
    expect(pending('save_trip')).toBeUndefined();
    expect(pending('get_weather')).toBeUndefined();
  });

  it('draws one for stays too', () => {
    const opening = pending('search_hotels')!.opening;
    expect(opsOf(opening)).toEqual(['createSurface', 'updateDataModel', 'updateComponents']);
    expect((opening[1] as any).updateDataModel.path).toBe('/hotels');
  });
});

describe('filling it', () => {
  /**
   * The point of binding everything: the components were sent once, and the
   * arrival of real flights must not re-send them. A `updateComponents` here
   * would mean the card the traveller is reading gets replaced underneath them.
   */
  it('moves the data model and nothing else', async () => {
    const found = await providerFor(undefined).searchFlights({
      destination: 'Madrid',
      origin: 'JFK',
      date: '2027-04-12',
    });
    expect(found.ok).toBe(true);
    if (!found.ok) return;

    const filled = pending('search_flights')!.fill({ flights: found.items })!;

    expect(opsOf(filled)).toEqual(['updateDataModel']);
    expect((filled[0] as any).updateDataModel.path).toBe('/flights');
    expect((filled[0] as any).updateDataModel.value).toHaveLength(found.items.length);
  });

  it('replaces the blank rows rather than patching over them', async () => {
    // Three results into four blank rows: patching row by row would leave the
    // fourth skeleton row on screen for good.
    const filled = pending('search_flights')!.fill({
      flights: [{ airline: 'Iberia' }, { airline: 'Delta' }, { airline: 'TAP' }],
    })!;
    expect((filled[0] as any).updateDataModel.value).toHaveLength(3);
  });

  it('does not fill from a refusal, which carries no rows', () => {
    expect(pending('search_flights')!.fill({ found: false, message: 'no' })).toBeNull();
    expect(pending('search_flights')!.fill({ flights: [] })).toBeNull();
    expect(pending('search_flights')!.fill(undefined)).toBeNull();
  });
});
