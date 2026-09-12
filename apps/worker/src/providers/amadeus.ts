/**
 * Live inventory, via the Amadeus Self-Service APIs.
 *
 * This exists so the seam is demonstrated rather than asserted. The repository's
 * claim is that a generative-UI app separates *what the agent says* from *where
 * the data came from*; a `TravelProvider` interface with exactly one
 * implementation would not have tested that claim at all.
 *
 * It ships unconfigured. With no `AMADEUS_CLIENT_ID` the app runs on fixtures,
 * which is the right default for a public demo — live search needs a credential,
 * has a quota, and returns different results every day, none of which a
 * screenshot or a test wants. Set the two variables and the same tools, the same
 * surfaces and the same components draw real fares:
 *
 *     npx wrangler secret put AMADEUS_CLIENT_ID --cwd apps/worker
 *     npx wrangler secret put AMADEUS_CLIENT_SECRET --cwd apps/worker
 *
 * Amadeus's test environment serves a cached subset of production inventory, so
 * "live" here means a real API with real failure modes — expired tokens, rate
 * limits, routes with no offers — rather than real-time pricing you could book.
 * Those failure modes are the interesting part: they are what a fixture cannot
 * teach you, and what `notFound` exists to carry.
 *
 * Weather is the one thing it does not serve, because Amadeus has no weather
 * product. Rather than invent one, `getWeather` delegates and the fixture's own
 * provenance travels with the answer — so in a live deployment the forecast card
 * is marked as sample data and the fare cards are not. Per-result provenance is
 * exactly for this.
 */

import { FixtureProvider } from './fixture.js';
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

export interface AmadeusConfig {
  clientId: string;
  clientSecret: string;
  /** Defaults to the test host. Production is `api.amadeus.com`. */
  host?: string;
}

const CABIN: Record<string, string> = {
  economy: 'ECONOMY',
  premium: 'PREMIUM_ECONOMY',
  business: 'BUSINESS',
  first: 'FIRST',
};

/** `PT7H35M` → `7h 35m`. Amadeus speaks ISO 8601 durations. */
function readDuration(iso: string): { label: string; minutes: number } {
  const match = /^PT(?:(\d+)H)?(?:(\d+)M)?$/.exec(iso ?? '');
  const hours = Number(match?.[1] ?? 0);
  const mins = Number(match?.[2] ?? 0);
  return { label: `${hours}h ${mins}m`, minutes: hours * 60 + mins };
}

/** `2027-04-12T08:15:00` → `08:15`, and `+1` when it lands the next day. */
function clockOf(iso: string, departure?: string): string {
  const time = (iso ?? '').slice(11, 16);
  if (!departure || !time) return time;
  const nextDay = iso.slice(0, 10) > departure.slice(0, 10) ? ' +1' : '';
  return `${time}${nextDay}`;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

export class AmadeusProvider implements TravelProvider {
  readonly provenance: Provenance;

  /** Fixtures still answer the questions Amadeus has no product for. */
  private readonly fallback = new FixtureProvider();

  private readonly host: string;
  private token: { value: string; expiresAt: number } | null = null;

  constructor(private readonly config: AmadeusConfig) {
    this.host = config.host ?? 'test.api.amadeus.com';
    this.provenance = {
      source: 'amadeus',
      live: true,
      label: this.host.startsWith('test.') ? 'Amadeus (test)' : 'Amadeus',
      detail:
        this.host.startsWith('test.')
          ? 'Live fares from the Amadeus test environment: a real API over a cached subset of inventory.'
          : 'Live fares from the Amadeus production API.',
    };
  }

  /**
   * A bearer token, cached until shortly before it expires.
   *
   * The 30-second margin is not superstition: a token that expires between the
   * check here and the request arriving produces a 401 that looks exactly like
   * a bad credential, and debugging that from a Worker log is unpleasant.
   */
  private async accessToken(): Promise<string> {
    const now = Date.now();
    if (this.token && this.token.expiresAt > now + 30_000) return this.token.value;

    const response = await fetch(`https://${this.host}/v1/security/oauth2/token`, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'client_credentials',
        client_id: this.config.clientId,
        client_secret: this.config.clientSecret,
      }),
    });

    if (!response.ok) {
      throw new Error(`Amadeus rejected the credentials (${response.status}).`);
    }

    const body = asRecord(await response.json());
    const value = String(body['access_token'] ?? '');
    if (!value) throw new Error('Amadeus returned no access token.');

    this.token = { value, expiresAt: now + Number(body['expires_in'] ?? 1799) * 1000 };
    return value;
  }

  private async get(path: string, params: Record<string, string | undefined>): Promise<unknown> {
    const url = new URL(`https://${this.host}${path}`);
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== '') url.searchParams.set(key, value);
    }
    const response = await fetch(url, {
      headers: { authorization: `Bearer ${await this.accessToken()}` },
    });
    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      throw new Error(`Amadeus ${path} returned ${response.status}. ${detail.slice(0, 200)}`);
    }
    return response.json();
  }

  /**
   * Errors become `notFound`, never an exception escaping into the tool loop.
   *
   * The cause is logged rather than shown: a traveler cannot act on "401 from
   * /v2/shopping/flight-offers", and a model handed that string will try to
   * explain it. What goes back is what to do next.
   */
  private failure(error: unknown, what: string): Outcome<never> {
    console.error(`amadeus: ${what} search failed`, error);
    return notFound(
      'upstream-error',
      this.provenance,
      `Live ${what} search is unavailable right now.`,
      ['Try again in a moment', 'Unset AMADEUS_CLIENT_ID to run on sample data'],
    );
  }

  async resolveDestination(query: string): Promise<Destination | undefined> {
    // City guidance — the highlights, the best months — is editorial and is not
    // something Amadeus sells. The fixture rows stay the source for it, and the
    // live provider is the source for prices.
    return this.fallback.resolveDestination(query);
  }

  async destinations(): Promise<Destination[]> {
    return this.fallback.destinations();
  }

  async origins(): Promise<OriginAirport[]> {
    return this.fallback.origins();
  }

  async searchFlights(query: FlightQuery): Promise<Outcome<Flight>> {
    const destination = await this.resolveDestination(query.destination);
    const destinationCode = destination?.airport;
    const origin = (query.origin ?? '').slice(0, 3).toUpperCase();

    if (!destinationCode) {
      return notFound(
        'unknown-destination',
        this.provenance,
        `Could not place “${query.destination}” as an airport.`,
        (await this.destinations()).map((entry) => `${entry.city}, ${entry.country}`),
      );
    }
    if (!origin) {
      return notFound('unknown-origin', this.provenance, 'Flights need somewhere to leave from.', [
        'Name a departure city',
      ]);
    }
    if (!query.date) {
      // Amadeus requires a departure date. Fixtures could invent one; a live
      // search must not, so this is a question rather than a guess.
      return notFound('no-coverage', this.provenance, 'A live fare search needs a departure date.', [
        'Pick the outbound date',
      ]);
    }

    try {
      const body = asRecord(
        await this.get('/v2/shopping/flight-offers', {
          originLocationCode: origin,
          destinationLocationCode: destinationCode,
          departureDate: query.date,
          adults: String(Math.max(1, query.travelers ?? 1)),
          travelClass: CABIN[query.cabin ?? 'economy'],
          nonStop: query.nonstopOnly ? 'true' : undefined,
          maxPrice: query.maxPrice ? String(Math.round(query.maxPrice)) : undefined,
          currencyCode: 'USD',
          max: '8',
        }),
      );

      const carriers = asRecord(asRecord(body['dictionaries'])['carriers']);
      const offers = asArray(body['data']);

      const flights: Flight[] = offers.flatMap((raw) => {
        const offer = asRecord(raw);
        const itinerary = asRecord(asArray(offer['itineraries'])[0]);
        const segments = asArray(itinerary['segments']).map(asRecord);
        const first = segments[0];
        const last = segments[segments.length - 1];
        if (!first || !last) return [];

        const departure = asRecord(first['departure']);
        const arrival = asRecord(last['arrival']);
        const departAt = String(departure['at'] ?? '');
        const carrier = String(first['carrierCode'] ?? '');
        const duration = readDuration(String(itinerary['duration'] ?? ''));
        const price = Number(asRecord(offer['price'])['grandTotal'] ?? 0);
        const stops = segments.length - 1;

        return [
          {
            id: String(offer['id'] ?? `${carrier}-${departAt}`),
            airline: String(carriers[carrier] ?? carrier),
            flightNumber: `${carrier}${String(first['number'] ?? '')}`,
            origin: String(departure['iataCode'] ?? origin),
            destination: String(arrival['iataCode'] ?? destinationCode),
            departTime: clockOf(departAt),
            arriveTime: clockOf(String(arrival['at'] ?? ''), departAt),
            duration: duration.label,
            stops:
              stops === 0
                ? 'Nonstop'
                : `${stops} stop${stops > 1 ? 's' : ''} · ${segments
                    .slice(0, -1)
                    .map((segment) => String(asRecord(segment['arrival'])['iataCode'] ?? ''))
                    .filter(Boolean)
                    .join(', ')}`,
            price: `$${Math.round(price).toLocaleString('en-US')}`,
            priceValue: Math.round(price),
            cabin: query.cabin ?? 'economy',
          },
        ];
      });

      if (flights.length === 0) {
        // A real "no inventory" answer, which is different from an error and
        // different again from an empty list nobody explained.
        return notFound(
          'no-coverage',
          this.provenance,
          `No fares on ${origin} → ${destinationCode} for ${query.date}.`,
          ['Try a nearby date', 'Allow a connection', 'Raise the price cap'],
        );
      }

      flights.sort((a, b) => a.priceValue - b.priceValue);
      flights[0]!.badge = 'Cheapest';
      const minutes = (flight: Flight) => {
        const match = /(\d+)h\s*(\d+)?/.exec(flight.duration);
        return match ? Number(match[1]) * 60 + Number(match[2] ?? 0) : Number.MAX_SAFE_INTEGER;
      };
      const fastest = [...flights].sort((a, b) => minutes(a) - minutes(b))[0];
      if (fastest && fastest.id !== flights[0]!.id) fastest.badge = 'Fastest';

      const shown = flights.slice(0, 4);
      return found(
        shown,
        this.provenance,
        `${shown.length} live fare(s) for ${origin} → ${destinationCode} on ${query.date}.`,
        [],
        'USD',
      );
    } catch (error) {
      return this.failure(error, 'flight');
    }
  }

  async searchHotels(query: HotelQuery): Promise<Outcome<Hotel>> {
    const destination = await this.resolveDestination(query.destination);
    if (!destination) {
      return notFound(
        'unknown-destination',
        this.provenance,
        `Could not place “${query.destination}”.`,
        (await this.destinations()).map((entry) => `${entry.city}, ${entry.country}`),
      );
    }

    try {
      const list = asRecord(
        await this.get('/v1/reference-data/locations/hotels/by-city', {
          cityCode: destination.airport,
          radius: '20',
          radiusUnit: 'KM',
        }),
      );

      const ids = asArray(list['data'])
        .map((entry) => String(asRecord(entry)['hotelId'] ?? ''))
        .filter(Boolean)
        .slice(0, 12);

      if (ids.length === 0) {
        return notFound(
          'no-coverage',
          this.provenance,
          `No bookable properties listed in ${destination.city}.`,
          ['Widen the area', 'Try another city'],
        );
      }

      const nights = Math.max(1, query.nights ?? 5);
      const checkIn = new Date(Date.now() + 30 * 86_400_000);
      const checkOut = new Date(checkIn.getTime() + nights * 86_400_000);

      const offers = asRecord(
        await this.get('/v3/shopping/hotel-offers', {
          hotelIds: ids.join(','),
          adults: String(Math.max(1, query.travelers ?? 2)),
          checkInDate: checkIn.toISOString().slice(0, 10),
          checkOutDate: checkOut.toISOString().slice(0, 10),
          currency: destination.currency,
          bestRateOnly: 'true',
        }),
      );

      const hotels: Hotel[] = asArray(offers['data']).flatMap((raw) => {
        const entry = asRecord(raw);
        const hotel = asRecord(entry['hotel']);
        const offer = asRecord(asArray(entry['offers'])[0]);
        const total = Number(asRecord(offer['price'])['total'] ?? 0);
        if (!total) return [];
        const nightly = total / nights;
        return [
          {
            id: String(hotel['hotelId'] ?? ''),
            name: String(hotel['name'] ?? 'Hotel'),
            neighborhood: destination.city,
            rating: String(hotel['rating'] ?? '—'),
            price: `${destination.currency} ${Math.round(nightly).toLocaleString('en-US')} / night`,
            priceValue: Math.round(nightly),
            amenities: asArray(hotel['amenities']).slice(0, 4).map(String),
          },
        ];
      });

      if (hotels.length === 0) {
        return notFound(
          'no-coverage',
          this.provenance,
          `No availability in ${destination.city} for ${nights} night(s).`,
          ['Try different dates', 'Change the party size'],
        );
      }

      hotels.sort((a, b) => a.priceValue - b.priceValue);
      hotels[0]!.badge = 'Best value';

      const shown = hotels.slice(0, 4);
      return found(
        shown,
        this.provenance,
        `${shown.length} live rate(s) in ${destination.city} for ${nights} night(s).`,
        [],
        destination.currency,
      );
    } catch (error) {
      return this.failure(error, 'hotel');
    }
  }

  async getWeather(destination: string, startDate?: string, days?: number): Promise<Outcome<Forecast>> {
    // Delegated, and the fixture's own provenance rides along — so the forecast
    // card says "Sample data" while the fares beside it do not.
    return this.fallback.getWeather(destination, startDate, days);
  }
}
