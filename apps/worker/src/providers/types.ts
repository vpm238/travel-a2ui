/**
 * The contract every travel data source answers, and the reason it exists.
 *
 * `travel.ts` used to be called directly by the tools, with a comment promising
 * that you could "swap these functions for real API calls and nothing above them
 * changes". That was an assertion, not a seam — and being an assertion, it hid
 * four ways for the app to answer a question with something that was not true:
 *
 *   - A price cap nothing matched returned `[]`, and the surface drew an empty
 *     box under a heading that said flights.
 *   - An unknown destination had its first three letters taken as an airport
 *     code, so "Reykjavik" produced four flights to "REY".
 *   - An unknown destination looking for a hotel fell back to `MAD`, so the same
 *     question came back as four Madrid hotels in Lavapiés, priced in euros,
 *     under the note "4 stay(s) in MAD".
 *   - Nothing anywhere said the numbers were invented.
 *
 * All four are the same bug: a function that could not say "I don't know" said
 * something else instead. So the type below makes not-knowing the only
 * alternative to knowing, and makes an empty success impossible to construct.
 */

/** Where an answer came from, carried with the answer rather than assumed. */
export interface Provenance {
  /** Stable id for the source: `fixture`, `amadeus`. */
  source: string;
  /** True when these numbers describe the real world. */
  live: boolean;
  /** Short enough for a badge on a card. */
  label: string;
  /** A sentence for a tooltip, a footer, or the model to repeat. */
  detail: string;
}

/**
 * A non-empty list.
 *
 * This is the whole trick. `[T, ...T[]]` cannot be `[]`, so a provider that
 * wants to report success has to have something to report, and the compiler —
 * not a reviewer, and not a test that someone remembers to write — is what
 * enforces it. `found()` below repeats the check at runtime for the boundaries
 * types do not reach, like JSON arriving from a real API.
 */
export type NonEmpty<T> = [T, ...T[]];

/** A provider found something. */
export interface Found<T> {
  ok: true;
  items: NonEmpty<T>;
  provenance: Provenance;
  /**
   * Filters dropped in order to have anything to show, named in the traveler's
   * words: `["the £400 cap", "nonstop only"]`.
   *
   * Relaxing silently would be its own dishonesty — a cheaper flight with a stop
   * is not the flight that was asked for. The surface says what it widened.
   */
  relaxed: string[];
  note: string;
  /**
   * The currency the prices are quoted in, when the items carry prices.
   *
   * Formatted into `price` already, and repeated here because the model is
   * allowed to re-derive a total and needs to know what to call it. A hotel in
   * Tokyo quoted in yen and totalled in dollars is a plausible-looking number
   * that is wrong by a factor of 150.
   */
  currency?: string;
}

/** Why a provider has nothing, in a form the agent can act on. */
export interface NotFound {
  ok: false;
  reason: 'unknown-destination' | 'unknown-origin' | 'no-coverage' | 'upstream-error';
  provenance: Provenance;
  /** Said to the traveler as-is. Never a stack trace, never a code. */
  message: string;
  /** Concrete things that would make this work. Rendered as choices. */
  recover: string[];
}

export type Outcome<T> = Found<T> | NotFound;

/**
 * Build a `Found`, or throw.
 *
 * The throw is deliberate and it is not defensive programming: reaching here
 * with an empty list means a provider decided it had succeeded at finding
 * nothing, and there is no sensible way to render that. Failing loudly in the
 * tool call gets the model a real error it can relay, which is strictly better
 * than a surface with a heading and no rows.
 */
export function found<T>(
  items: readonly T[],
  provenance: Provenance,
  note: string,
  relaxed: string[] = [],
  currency?: string,
): Found<T> {
  if (items.length === 0) {
    throw new Error(
      `${provenance.source} reported success with no results. ` +
        'A provider with nothing to show must return `notFound` and say why.',
    );
  }
  return { ok: true, items: items as unknown as NonEmpty<T>, provenance, note, relaxed, currency };
}

export function notFound(
  reason: NotFound['reason'],
  provenance: Provenance,
  message: string,
  recover: string[],
): NotFound {
  return { ok: false, reason, provenance, message, recover };
}

export interface Destination {
  city: string;
  country: string;
  airport: string;
  currency: string;
  bestMonths: string;
  summary: string;
  highlights: Array<{ name: string; category: string; note: string }>;
  neighbourhoods: string[];
}

export interface Flight {
  id: string;
  airline: string;
  flightNumber: string;
  origin: string;
  destination: string;
  departTime: string;
  arriveTime: string;
  duration: string;
  stops: string;
  price: string;
  priceValue: number;
  cabin: string;
  badge?: string;
}

export interface Hotel {
  id: string;
  name: string;
  neighborhood: string;
  rating: string;
  price: string;
  priceValue: number;
  amenities: string[];
  badge?: string;
}

export interface OriginAirport {
  code: string;
  city: string;
  zones: string[];
}

export interface Forecast {
  place: string;
  days: Array<{ day: string; high: string; low: string; condition: string }>;
  note: string;
}

export interface FlightQuery {
  origin?: string;
  destination: string;
  date?: string;
  travelers?: number;
  cabin?: string;
  maxPrice?: number;
  nonstopOnly?: boolean;
  /**
   * The traveler asked what a trip like this *generally* costs, rather than
   * what theirs costs.
   *
   * It lets a provider answer without a departure city — but never by quietly
   * choosing one. A provider that samples an origin has to name it in
   * `relaxed`, which the surface renders. The old code defaulted to JFK and
   * said nothing, so somebody in Berlin was shown transatlantic fares as if
   * they were their own.
   */
  indicative?: boolean;
}

export interface HotelQuery {
  destination: string;
  nights?: number;
  travelers?: number;
  maxNightly?: number;
  neighborhood?: string;
}

/**
 * A source of travel data.
 *
 * Async throughout, including in the fixture implementation that has nothing to
 * await. A synchronous interface would have meant every caller changing shape
 * the day a real provider arrived, which is exactly the kind of "swap and
 * nothing above changes" claim this file exists to stop making on credit.
 */
export interface TravelProvider {
  readonly provenance: Provenance;

  /** Resolves free text to a place, or nothing. Nothing is a real answer. */
  resolveDestination(query: string): Promise<Destination | undefined>;

  /** Everywhere this provider can talk about. Used to offer alternatives. */
  destinations(): Promise<Destination[]>;

  origins(): Promise<OriginAirport[]>;

  searchFlights(query: FlightQuery): Promise<Outcome<Flight>>;

  searchHotels(query: HotelQuery): Promise<Outcome<Hotel>>;

  getWeather(destination: string, startDate?: string, days?: number): Promise<Outcome<Forecast>>;
}
