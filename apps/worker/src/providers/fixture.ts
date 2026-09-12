/**
 * The deterministic fixture provider.
 *
 * Same generator as before — a seeded RNG over the rows in `data/` — with the
 * four ways it used to lie removed:
 *
 *   - An unknown destination is now `notFound`, with the cities it does know
 *     offered as choices. It no longer takes the first three letters of
 *     "Reykjavik" as an airport code, and no longer quietly answers with Madrid.
 *   - A filter that matches nothing relaxes, one constraint at a time, and says
 *     which. `relaxed` is rendered; widening silently would be its own lie.
 *   - Every result carries `provenance`, so the surface can mark it as sample
 *     data without anybody having to remember to.
 *
 * Determinism is the point of this provider and is pinned by a golden file. The
 * same query returns the same flights on every run, so a screenshot stays true
 * and a test can assert on a price.
 */

import {
  AIRLINES,
  AMENITIES,
  CONNECTIONS,
  CURRENCY_SYMBOL,
  DESTINATIONS,
  HOTEL_NAMES,
  HOTEL_WORDS,
  ORIGINS,
} from './fixtures.generated.js';
import {
  found,
  notFound,
  type Destination,
  type Flight,
  type FlightQuery,
  type Forecast,
  type Hotel,
  type HotelQuery,
  type OriginAirport,
  type Outcome,
  type Provenance,
  type TravelProvider,
} from './types.js';

export const FIXTURE_PROVENANCE: Provenance = {
  source: 'fixture',
  live: false,
  label: 'Sample data',
  detail:
    'Prices, schedules and hotels are generated for this demo and are not real. ' +
    'City guidance is real. Set AMADEUS_CLIENT_ID to search live inventory.',
};

/**
 * FNV-1a. Four lines, no dependencies, and it spreads short strings like
 * "MAD-2027-04-12" well enough that two adjacent dates do not produce the same
 * itinerary.
 */
function seed(input: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

function rng(state: number): () => number {
  let value = state || 1;
  return () => {
    value ^= value << 13;
    value ^= value >>> 17;
    value ^= value << 5;
    value >>>= 0;
    return value / 0xffffffff;
  };
}

const pick = <T>(items: readonly T[], random: () => number): T =>
  items[Math.floor(random() * items.length) % items.length]!;

const DESTINATION_LIST: Destination[] = DESTINATIONS.map((entry) => ({
  city: entry.city,
  country: entry.country,
  airport: entry.airport,
  currency: entry.currency,
  bestMonths: entry.bestMonths,
  summary: entry.summary,
  highlights: entry.highlights.map((h) => ({ ...h })),
  neighbourhoods: [...entry.neighbourhoods],
}));

const BY_CODE = new Map(DESTINATION_LIST.map((entry) => [entry.airport, entry]));

const BY_ALIAS = new Map<string, Destination>();
for (const [index, entry] of DESTINATIONS.entries()) {
  for (const alias of entry.aliases) BY_ALIAS.set(alias, DESTINATION_LIST[index]!);
}

function money(amount: number, currency: string): string {
  const symbol = (CURRENCY_SYMBOL as Record<string, string>)[currency] ?? `${currency} `;
  return `${symbol}${Math.round(amount).toLocaleString('en-US')}`;
}

function clockTime(minutes: number): string {
  const wrapped = ((minutes % 1440) + 1440) % 1440;
  const hours = Math.floor(wrapped / 60);
  const mins = wrapped % 60;
  const nextDay = minutes >= 1440 ? ' +1' : '';
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}${nextDay}`;
}

function durationMinutes(duration: string): number {
  const match = /(\d+)h\s*(\d+)?/.exec(duration);
  return match ? Number(match[1]) * 60 + Number(match[2] ?? 0) : 0;
}

/** Resolution, without the substring guessing that used to invent airports. */
function resolve(query: string): Destination | undefined {
  const trimmed = (query ?? '').trim();
  if (!trimmed) return undefined;
  const exact = BY_CODE.get(trimmed.toUpperCase());
  if (exact) return exact;
  const alias = BY_ALIAS.get(trimmed.toLowerCase());
  if (alias) return alias;
  // A phrase like "a few days in Madrid" still resolves, but only by containing
  // a name we actually know — never by slicing three characters off the front.
  const lowered = trimmed.toLowerCase();
  for (const [name, entry] of BY_ALIAS) {
    if (lowered.includes(name)) return entry;
  }
  return undefined;
}

/** What to offer when we cannot place somewhere. */
function elsewhere(): string[] {
  return DESTINATION_LIST.map((entry) => `${entry.city}, ${entry.country}`);
}

function unknownDestination(query: string) {
  const places = elsewhere();
  return notFound(
    'unknown-destination',
    FIXTURE_PROVENANCE,
    // Counted rather than written down. It said "six cities" for exactly as
    // long as it took to add three more.
    `This demo does not have data for “${query}”. It covers ${places.length} cities.`,
    places,
  );
}

/**
 * Drop filters until something survives, and report what was dropped.
 *
 * Order matters and is a judgement: a price cap is the constraint a traveler is
 * most often willing to hear about being exceeded ("the cheapest is £430"),
 * while a nonstop requirement is often non-negotiable, so the cap goes first.
 * Whatever is dropped is named in the traveler's words and shown.
 */
function relaxUntilNonEmpty<T>(
  all: readonly T[],
  filters: Array<{ label: string; keep: (item: T) => boolean }>,
): { items: T[]; relaxed: string[] } {
  const active = [...filters];
  const relaxed: string[] = [];

  for (;;) {
    const items = all.filter((item) => active.every((filter) => filter.keep(item)));
    if (items.length > 0 || active.length === 0) return { items, relaxed };
    relaxed.push(active.shift()!.label);
  }
}

export class FixtureProvider implements TravelProvider {
  readonly provenance = FIXTURE_PROVENANCE;

  async resolveDestination(query: string): Promise<Destination | undefined> {
    return resolve(query);
  }

  async destinations(): Promise<Destination[]> {
    return DESTINATION_LIST;
  }

  async origins(): Promise<OriginAirport[]> {
    return ORIGINS.map((entry) => ({ ...entry, zones: [...entry.zones] }));
  }

  async searchFlights(query: FlightQuery): Promise<Outcome<Flight>> {
    const destination = resolve(query.destination);
    if (!destination) return unknownDestination(query.destination);

    let origin = (query.origin ?? '').slice(0, 3).toUpperCase();
    const sampled: string[] = [];
    if (!origin) {
      if (!query.indicative) {
        return notFound(
          'unknown-origin',
          FIXTURE_PROVENANCE,
          'Flights need somewhere to leave from.',
          ORIGINS.slice(0, 6).map((entry) => `${entry.city} (${entry.code})`),
        );
      }
      // An explicitly rough question can be answered without a departure city,
      // but not by pretending to have one. The sample is named and shown.
      const standIn = ORIGINS[0]!;
      origin = standIn.code;
      sampled.push(`no departure city — sampled from ${standIn.city} (${standIn.code})`);
    }

    const date = query.date ?? '';
    const cabin = query.cabin ?? 'economy';
    const random = rng(seed(`${origin}-${destination.airport}-${date}-${cabin}`));
    const cabinMultiplier =
      ({ economy: 1, premium: 1.7, business: 3.4, first: 5.6 } as Record<string, number>)[cabin] ?? 1;
    const base = 280 + random() * 260;

    const all: Flight[] = [];
    const used = new Set<string>();
    for (let index = 0; index < 5; index++) {
      let airline = pick(AIRLINES, random);
      let guard = 0;
      while (used.has(airline.code) && guard++ < 8) airline = pick(AIRLINES, random);
      used.add(airline.code);

      const stops = index === 4 || random() < 0.28;
      const departMinutes = Math.floor(6 * 60 + random() * 15 * 60);
      const legMinutes = Math.floor((stops ? 620 : 430) + random() * 140);
      const price = base * cabinMultiplier * (stops ? 0.82 : 1) * (0.9 + random() * 0.4);

      all.push({
        id: `${airline.code}${1000 + Math.floor(random() * 8000)}`,
        airline: airline.name,
        flightNumber: `${airline.code}${100 + Math.floor(random() * 899)}`,
        origin,
        destination: destination.airport,
        departTime: clockTime(departMinutes),
        arriveTime: clockTime(departMinutes + legMinutes),
        duration: `${Math.floor(legMinutes / 60)}h ${legMinutes % 60}m`,
        stops: stops ? `1 stop · ${pick(CONNECTIONS, random)}` : 'Nonstop',
        price: money(price, 'USD'),
        priceValue: Math.round(price),
        cabin,
      });
    }

    const { items, relaxed: dropped } = relaxUntilNonEmpty(all, [
      ...(query.maxPrice
        ? [
            {
              label: `the ${money(query.maxPrice, 'USD')} cap`,
              keep: (flight: Flight) => flight.priceValue <= query.maxPrice!,
            },
          ]
        : []),
      ...(query.nonstopOnly
        ? [{ label: 'nonstop only', keep: (flight: Flight) => flight.stops === 'Nonstop' }]
        : []),
    ]);

    const relaxed = [...sampled, ...dropped];
    items.sort((a, b) => a.priceValue - b.priceValue);
    items[0]!.badge = 'Cheapest';
    const fastest = [...items].sort(
      (a, b) => durationMinutes(a.duration) - durationMinutes(b.duration),
    )[0]!;
    if (fastest.id !== items[0]!.id) fastest.badge = 'Fastest';

    const shown = items.slice(0, 4);
    const where = `${origin} → ${destination.airport}${date ? ` on ${date}` : ''}`;
    const note = [
      dropped.length
        ? `Nothing matched ${dropped.join(' and ')} — closest ${shown.length} for ${where}.`
        : `${shown.length} option(s) for ${where}.`,
      sampled.length ? `Typical fares: ${sampled.join('; ')}.` : '',
    ]
      .filter(Boolean)
      .join(' ');

    return found(shown, FIXTURE_PROVENANCE, note, relaxed, 'USD');
  }

  async searchHotels(query: HotelQuery): Promise<Outcome<Hotel>> {
    const destination = resolve(query.destination);
    if (!destination) return unknownDestination(query.destination);

    const code = destination.airport;
    const currency = destination.currency;
    const nights = query.nights ?? 5;
    const random = rng(seed(`hotels-${code}-${nights}-${query.neighborhood ?? ''}`));
    const areas = destination.neighbourhoods.length ? destination.neighbourhoods : ['Centre'];

    const all: Hotel[] = [];
    for (let index = 0; index < 5; index++) {
      const nightly = 95 + random() * 240;
      const amenityCount = 2 + Math.floor(random() * 3);
      const amenities: string[] = [];
      // Bounded, like the airline picker above. Drawing distinct values out of
      // a seeded sequence terminates in practice rather than by construction,
      // and an unbounded loop here is a hung request rather than a wrong answer.
      let guard = 0;
      while (amenities.length < amenityCount && guard++ < 32) {
        const amenity = pick(AMENITIES, random);
        if (!amenities.includes(amenity)) amenities.push(amenity);
      }
      all.push({
        id: `h_${code}_${index}`,
        name: `${pick(HOTEL_WORDS, random)} ${pick(HOTEL_NAMES, random)}`,
        neighborhood: query.neighborhood || pick(areas, random),
        rating: `${(3.9 + random() * 1.05).toFixed(1)} (${200 + Math.floor(random() * 1800)})`,
        price: `${money(nightly, currency)} / night`,
        priceValue: Math.round(nightly),
        amenities,
      });
    }

    const { items, relaxed } = relaxUntilNonEmpty(all, [
      ...(query.maxNightly
        ? [
            {
              label: `the ${money(query.maxNightly, currency)} a night cap`,
              keep: (hotel: Hotel) => hotel.priceValue <= query.maxNightly!,
            },
          ]
        : []),
    ]);

    items.sort((a, b) => a.priceValue - b.priceValue);
    items[0]!.badge = 'Best value';
    if (items.length > 2) items[items.length - 1]!.badge = 'Most central';

    const shown = items.slice(0, 4);
    const note = relaxed.length
      ? `Nothing under ${relaxed.join(' and ')}. Closest ${shown.length} in ${destination.city}.`
      : `${shown.length} stay(s) in ${destination.city} for ${nights} night(s).`;

    return found(shown, FIXTURE_PROVENANCE, note, relaxed, currency);
  }

  async getWeather(destinationQuery: string, startDate?: string, days = 5): Promise<Outcome<Forecast>> {
    const destination = resolve(destinationQuery);
    if (!destination) return unknownDestination(destinationQuery);

    const start = startDate ? new Date(startDate) : new Date();
    const random = rng(seed(`weather-${destination.city}-${startDate ?? ''}`));
    const conditions = ['sun', 'sun', 'cloud', 'cloud', 'rain', 'fog'] as const;
    const weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] as const;

    const forecast = [];
    let high = 14 + random() * 12;
    for (let index = 0; index < Math.min(Math.max(days, 1), 7); index++) {
      high += random() * 6 - 3;
      const low = high - (5 + random() * 4);
      const date = new Date(start.getTime() + index * 86_400_000);
      forecast.push({
        day: weekdays[date.getUTCDay()] ?? 'Day',
        high: `${Math.round(high)}°`,
        low: `${Math.round(low)}°`,
        condition: pick(conditions, random),
      });
    }

    const wet = forecast.filter((entry) => entry.condition === 'rain').length;
    const note = wet > 1 ? 'Rain on more than one day — pack a shell.' : 'Mostly dry; a light jacket is enough.';

    return found([{ place: destination.city, days: forecast, note }], FIXTURE_PROVENANCE, note);
  }
}
