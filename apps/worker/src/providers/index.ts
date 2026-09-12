/**
 * Which data source answers, decided once per request from the environment.
 *
 * The rule is deliberately blunt: credentials present means live, credentials
 * absent means fixtures. There is no `PROVIDER=live` flag, because a flag can
 * be set without a credential and the failure then arrives on the traveler's
 * screen instead of at startup.
 *
 * Whichever is chosen, the answer carries its own `provenance`, so nothing
 * downstream has to know or ask.
 */

import { AmadeusProvider } from './amadeus.js';
import { FixtureProvider } from './fixture.js';
import type { TravelProvider } from './types.js';

export interface ProviderEnv {
  AMADEUS_CLIENT_ID?: string;
  AMADEUS_CLIENT_SECRET?: string;
  AMADEUS_HOST?: string;
}

const fixtures = new FixtureProvider();

/** Cached per credential pair: the token inside a provider is worth keeping. */
const live = new Map<string, AmadeusProvider>();

export function providerFor(env: ProviderEnv | undefined): TravelProvider {
  const clientId = env?.AMADEUS_CLIENT_ID?.trim();
  const clientSecret = env?.AMADEUS_CLIENT_SECRET?.trim();
  if (!clientId || !clientSecret) return fixtures;

  const key = `${clientId}:${env?.AMADEUS_HOST ?? ''}`;
  let provider = live.get(key);
  if (!provider) {
    provider = new AmadeusProvider({ clientId, clientSecret, host: env?.AMADEUS_HOST });
    live.set(key, provider);
  }
  return provider;
}

export { FixtureProvider, FIXTURE_PROVENANCE } from './fixture.js';
export { AmadeusProvider } from './amadeus.js';
export * from './types.js';
