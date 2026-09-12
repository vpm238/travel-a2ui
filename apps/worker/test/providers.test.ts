/**
 * The provider contract, and the four lies it was written to stop.
 *
 * Each of these was a real behaviour of the code this replaced, found by
 * capturing its output rather than by reading it — which is the only reason
 * they were found at all, since every one of them returned something that
 * looked entirely plausible on screen.
 */

import { describe, expect, it } from 'vitest';

import { FixtureProvider, found, providerFor, FIXTURE_PROVENANCE } from '../src/providers/index.js';

const provider = new FixtureProvider();

describe('a destination the provider does not know', () => {
  /**
   * It used to take the first three letters as an airport code, so "Reykjavik"
   * came back as four flights to "REY" — a place, at that price, on that day,
   * none of which existed.
   */
  it('refuses rather than inventing an airport code', async () => {
    const outcome = await provider.searchFlights({ destination: 'Reykjavik', origin: 'JFK' });

    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(outcome.reason).toBe('unknown-destination');
    expect(JSON.stringify(outcome)).not.toContain('REY');
  });

  /**
   * The worse one. Hotels fell back to `MAD`, so a question about Iceland came
   * back as four Madrid hotels in Lavapiés, priced in euros, captioned
   * "4 stay(s) in MAD".
   */
  it('refuses rather than quietly answering about Madrid', async () => {
    const outcome = await provider.searchHotels({ destination: 'Reykjavik', nights: 4 });

    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(outcome.reason).toBe('unknown-destination');
    // Not a substring search over the whole object: "AMADEUS_CLIENT_ID" in the
    // provenance detail contains "MAD", and an assertion that trips on that is
    // testing the wrong thing. What matters is the sentence the traveler reads
    // and the fact that no Madrid inventory came back at all.
    expect(outcome.message).toContain('Reykjavik');
    expect(outcome.message).not.toMatch(/madrid|lavapi/i);
    expect(outcome).not.toHaveProperty('items');
  });

  it('offers somewhere it does know, so the refusal has a next step', async () => {
    const outcome = await provider.searchFlights({ destination: 'Atlantis', origin: 'JFK' });

    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(outcome.recover).toContain('Madrid, Spain');
  });

  it('counts the cities it knows rather than claiming a number', async () => {
    const outcome = await provider.searchFlights({ destination: 'Atlantis', origin: 'JFK' });
    const total = (await provider.destinations()).length;

    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(outcome.message).toContain(`${total} cities`);
    expect(outcome.recover).toHaveLength(total);
  });
});

describe('a filter that matches nothing', () => {
  /** This returned `[]`, and the surface drew a heading over an empty box. */
  it('widens rather than showing an empty list', async () => {
    const outcome = await provider.searchFlights({
      destination: 'Tokyo',
      origin: 'LAX',
      maxPrice: 1,
    });

    expect(outcome.ok).toBe(true);
    if (!outcome.ok) return;
    expect(outcome.items.length).toBeGreaterThan(0);
  });

  it('says what it widened, in words a traveler can read', async () => {
    const outcome = await provider.searchFlights({
      destination: 'Tokyo',
      origin: 'LAX',
      maxPrice: 1,
    });

    expect(outcome.ok).toBe(true);
    if (!outcome.ok) return;
    expect(outcome.relaxed).toEqual(['the $1 cap']);
    expect(outcome.note).toContain('Nothing matched');
  });

  /**
   * Order is a judgement rather than an accident: a price cap is the constraint
   * a traveler most often wants to hear has been exceeded, so it goes first and
   * a nonstop requirement survives longer.
   */
  it('drops the price cap before the nonstop requirement', async () => {
    const outcome = await provider.searchFlights({
      destination: 'Madrid',
      origin: 'JFK',
      maxPrice: 1,
      nonstopOnly: true,
    });

    expect(outcome.ok).toBe(true);
    if (!outcome.ok) return;
    expect(outcome.relaxed[0]).toContain('cap');
    expect(outcome.items.every((flight) => flight.stops === 'Nonstop')).toBe(true);
  });

  it('widens the nightly cap for hotels too', async () => {
    const outcome = await provider.searchHotels({ destination: 'Paris', nights: 3, maxNightly: 1 });

    expect(outcome.ok).toBe(true);
    if (!outcome.ok) return;
    expect(outcome.items.length).toBeGreaterThan(0);
    expect(outcome.relaxed).toHaveLength(1);
  });
});

describe('a missing departure city', () => {
  it('asks, when the traveler is pricing their own trip', async () => {
    const outcome = await provider.searchFlights({ destination: 'Madrid' });

    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(outcome.reason).toBe('unknown-origin');
  });

  /**
   * The old default was JFK, silently, so someone in Berlin asking what a week
   * in Madrid costs was shown transatlantic fares as though they were theirs.
   */
  it('names the city it sampled, when asked for a rough figure', async () => {
    const outcome = await provider.searchFlights({ destination: 'Madrid', indicative: true });

    expect(outcome.ok).toBe(true);
    if (!outcome.ok) return;
    expect(outcome.relaxed.join(' ')).toContain('New York');
    expect(outcome.note).toContain('Typical fares');
  });
});

describe('provenance', () => {
  it('rides along with every answer, so nothing has to remember to add it', async () => {
    const flights = await provider.searchFlights({ destination: 'Madrid', origin: 'JFK' });
    const hotels = await provider.searchHotels({ destination: 'Madrid', nights: 3 });
    const weather = await provider.getWeather('Madrid');

    for (const outcome of [flights, hotels, weather]) {
      expect(outcome.provenance.source).toBe('fixture');
      expect(outcome.provenance.live).toBe(false);
      expect(outcome.provenance.label).toBe('Sample data');
    }
  });

  it('says in its detail that the numbers are not real', async () => {
    expect(FIXTURE_PROVENANCE.detail).toMatch(/not real/i);
  });
});

describe('the no-empty-success guarantee', () => {
  /**
   * The type makes this unrepresentable — `items` is `[T, ...T[]]` — so this
   * asserts the runtime half, which is what a real API's JSON reaches.
   */
  it('throws rather than letting a provider succeed at finding nothing', () => {
    expect(() => found([], FIXTURE_PROVENANCE, 'nothing here')).toThrowError(/no results/i);
  });

  it('keeps a non-empty list intact', () => {
    const outcome = found([{ id: 'a' }], FIXTURE_PROVENANCE, 'one');
    expect(outcome.ok).toBe(true);
    expect(outcome.items).toHaveLength(1);
  });
});

describe('choosing a provider', () => {
  it('falls back to fixtures when no credential is configured', () => {
    expect(providerFor(undefined).provenance.source).toBe('fixture');
    expect(providerFor({}).provenance.source).toBe('fixture');
    expect(providerFor({ AMADEUS_CLIENT_ID: '   ' }).provenance.source).toBe('fixture');
  });

  /** A half-configured deployment is a configuration bug, not a live one. */
  it('does not go live on an id with no secret', () => {
    expect(providerFor({ AMADEUS_CLIENT_ID: 'abc' }).provenance.source).toBe('fixture');
  });

  it('goes live when both halves are present', () => {
    const provenance = providerFor({
      AMADEUS_CLIENT_ID: 'abc',
      AMADEUS_CLIENT_SECRET: 'shh',
    }).provenance;

    expect(provenance.source).toBe('amadeus');
    expect(provenance.live).toBe(true);
  });

  it('reuses one provider per credential, so its token survives', () => {
    const env = { AMADEUS_CLIENT_ID: 'abc', AMADEUS_CLIENT_SECRET: 'shh' };
    expect(providerFor(env)).toBe(providerFor(env));
  });
});
