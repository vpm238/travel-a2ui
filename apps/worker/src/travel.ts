/**
 * The two pieces of travel logic that are not a data source.
 *
 * Everything else that used to live here — flights, hotels, forecasts, city
 * guides — moved to `providers/`, behind an interface with two implementations
 * and a contract that makes "success with no results" impossible to express.
 * See `providers/types.ts` for why that was worth doing.
 *
 * What stayed is what no provider owns:
 *
 *   - `estimateTrip` is arithmetic over numbers the caller already has. It
 *     queries nothing, so putting it behind an async interface would have been
 *     ceremony.
 *   - `originForTimeZone` turns a browser's timezone into a *suggestion* about
 *     where someone is flying from. Which airports exist is data, and comes
 *     from `data/origins.csv` like everything else; which one a timezone
 *     suggests is a rule, and lives here.
 */

import { CURRENCY_SYMBOL, DESTINATIONS, ORIGINS } from './providers/fixtures.generated.js';
import type { OriginAirport } from './providers/types.js';

export type { OriginAirport } from './providers/types.js';

/** FNV-1a, so an estimate for the same trip comes back the same every time. */
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

function money(amount: number, currency: string): string {
  const symbol = (CURRENCY_SYMBOL as Record<string, string>)[currency] ?? `${currency} `;
  return `${symbol}${Math.round(amount).toLocaleString('en-US')}`;
}

/**
 * The airport code a destination name maps to, for seeding only.
 *
 * Deliberately not exported, and deliberately not the provider's resolver: this
 * exists so that "Madrid" and "MAD" produce the same estimate, and nothing more.
 * A caller that wants to know whether a place is real asks the provider, which
 * can say no.
 */
function codeForSeed(query: string): string {
  const trimmed = (query ?? '').trim();
  const upper = trimmed.toUpperCase();
  const lowered = trimmed.toLowerCase();
  for (const entry of DESTINATIONS) {
    if (entry.airport === upper) return entry.airport;
    if ((entry.aliases as readonly string[]).includes(lowered)) return entry.airport;
  }
  return trimmed;
}

export function knownOrigins(): OriginAirport[] {
  return ORIGINS.map((entry) => ({ ...entry, zones: [...entry.zones] }));
}

/**
 * The airport a timezone suggests, or nothing.
 *
 * Returning nothing is a perfectly good answer — better than reaching for the
 * nearest continent. The caller offers what it gets as a pre-filled choice the
 * traveler confirms, and asks outright when there is nothing to offer.
 */
export function originForTimeZone(timeZone: string | undefined): OriginAirport | undefined {
  if (!timeZone) return undefined;
  const exact = ORIGINS.find((entry) => (entry.zones as readonly string[]).includes(timeZone));
  if (exact) return { ...exact, zones: [...exact.zones] };
  // Fall back to the region only: 'Europe/Warsaw' is not listed, but a European
  // hub is a far better prompt than New York.
  const region = timeZone.split('/')[0];
  const nearby = ORIGINS.find((entry) =>
    (entry.zones as readonly string[]).some((zone) => zone.split('/')[0] === region),
  );
  return nearby ? { ...nearby, zones: [...nearby.zones] } : undefined;
}

export interface PriceEstimate {
  lines: Array<{ label: string; amount: string; note?: string }>;
  total: string;
  totalValue: number;
  currency: string;
}

/**
 * What a trip comes to, line by line.
 *
 * Flight and nightly figures are passed in when the traveler has chosen them,
 * so the total describes their trip rather than an average. Where they have
 * not, a seeded figure stands in — which is why `basis` accompanies this
 * everywhere it is shown: a total with no party size and no length beside it is
 * a number nobody can check.
 */
export function estimateTrip(input: {
  destination: string;
  travelers?: number;
  nights?: number;
  flightPrice?: number;
  nightlyPrice?: number;
}): PriceEstimate {
  const currency = 'USD';
  const travelers = Math.max(1, input.travelers ?? 2);
  const nights = Math.max(1, input.nights ?? 5);
  const random = rng(seed(`estimate-${codeForSeed(input.destination)}-${travelers}-${nights}`));

  const flight = (input.flightPrice ?? 380 + random() * 180) * travelers;
  const stay = (input.nightlyPrice ?? 140 + random() * 90) * nights;
  const food = 55 * travelers * (nights + 1);
  const local = 24 * (nights + 1);

  const lines = [
    { label: `Flights (${travelers} traveler${travelers > 1 ? 's' : ''})`, amount: money(flight, currency) },
    { label: `Stay (${nights} night${nights > 1 ? 's' : ''})`, amount: money(stay, currency) },
    { label: 'Food and drink', amount: money(food, currency), note: 'estimated' },
    { label: 'Local transport', amount: money(local, currency), note: 'metro and taxis' },
  ];

  const total = flight + stay + food + local;
  return { lines, total: money(total, currency), totalValue: Math.round(total), currency };
}
