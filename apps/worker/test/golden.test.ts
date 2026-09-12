/**
 * The fixtures are supposed to be deterministic. This is what makes that a fact.
 *
 * `travel.ts` claims in its header that "the same query returns the same flights
 * on every run, so a screenshot stays true, a test can assert on a price". That
 * was an assertion about a seeded RNG, not a test — nothing stopped a refactor
 * from quietly re-ordering a `pick()` and changing every price in the demo.
 *
 * So: a golden file. The first run writes it, every run after compares. It also
 * pins the behaviour across the move of this data out of TypeScript and into
 * `data/`, which is the point at which it would otherwise have been easy to lose
 * a row and never notice.
 *
 * Regenerate deliberately, and read the diff before you commit it:
 *
 *     rm apps/worker/test/__golden__/travel.json && npm test
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { estimateTrip } from '../src/travel.js';
import { providerFor } from '../src/providers/index.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const GOLDEN = join(HERE, '__golden__', 'travel.json');

/**
 * Queries chosen to cover the branches, not to look pretty.
 *
 * Three of them are the interesting ones: a filter that empties the list, a
 * destination nobody knows, and a cabin that multiplies the price.
 */
const provider = providerFor(undefined);

const CASES = {
  'flights: madrid, plain': () => provider.searchFlights({ destination: 'Madrid', origin: 'JFK' }),
  'flights: dated and business': () =>
    provider.searchFlights({ destination: 'Madrid', origin: 'JFK', date: '2027-04-12', cabin: 'business' }),
  'flights: nonstop only': () =>
    provider.searchFlights({ destination: 'Lisbon', origin: 'BOS', nonstopOnly: true }),
  'flights: impossible price cap': () =>
    provider.searchFlights({ destination: 'Tokyo', origin: 'LAX', maxPrice: 1 }),
  'flights: destination nobody knows': () =>
    provider.searchFlights({ destination: 'Reykjavik', origin: 'JFK' }),
  'flights: no departure city, and not asked to guess': () =>
    provider.searchFlights({ destination: 'Madrid' }),
  'flights: no departure city, explicitly rough': () =>
    provider.searchFlights({ destination: 'Madrid', indicative: true }),
  'hotels: madrid, five nights': () => provider.searchHotels({ destination: 'Madrid', nights: 5 }),
  'hotels: impossible nightly cap': () =>
    provider.searchHotels({ destination: 'Paris', nights: 3, maxNightly: 1 }),
  'hotels: destination nobody knows': () => provider.searchHotels({ destination: 'Reykjavik', nights: 4 }),
  'weather: madrid in april': () => provider.getWeather('Madrid', '2027-04-12', 5),
  'estimate: two travelers, seven nights': async () =>
    estimateTrip({ destination: 'Madrid', travelers: 2, nights: 7 }),
};

const capture = async () =>
  Object.fromEntries(
    await Promise.all(Object.entries(CASES).map(async ([name, run]) => [name, await run()])),
  );

describe('the travel fixtures', () => {
  it('return the same thing every time', async () => {
    const now = await capture();

    if (!existsSync(GOLDEN)) {
      mkdirSync(dirname(GOLDEN), { recursive: true });
      writeFileSync(GOLDEN, `${JSON.stringify(now, null, 2)}\n`, 'utf-8');
      // Not a pass disguised as a pass: say what happened.
      console.warn(`Wrote a new golden file at ${GOLDEN}. Read it before committing.`);
      return;
    }

    expect(now).toEqual(JSON.parse(readFileSync(GOLDEN, 'utf-8')));
  });

  it('are stable across repeated calls in one process', async () => {
    expect(await capture()).toEqual(await capture());
  });
});
