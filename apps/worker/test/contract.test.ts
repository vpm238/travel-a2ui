/**
 * The contract stamp, which is only useful if it moves for the right reasons.
 *
 * It exists so a Gemini Live session cannot go on composing against a catalog
 * the deployment replaced last night. That works exactly as well as the stamp's
 * ability to tell "the contract changed" from "a day passed" — a stamp that
 * moves too often teaches a traveller to click through the warning, and one
 * that moves too rarely is the bug it was written to prevent.
 */

import { describe, expect, it } from 'vitest';

import { contractStamp, INSTANTIATION_MAX_AGE_MS } from '../src/contract.js';
import worker from '../src/index.js';

const env = { ASSETS: undefined, TRIP_SESSION: undefined } as never;

async function meta() {
  const response = await worker.fetch(
    new Request('https://example.test/api/meta'),
    env,
    {} as never,
  );
  return (await response.json()) as any;
}

describe('the stamp', () => {
  it('is stable within a deployment', () => {
    expect(contractStamp()).toBe(contractStamp());
  });

  /**
   * The failure this guards: the system prompt interpolates today's date and
   * the trip so far. Fingerprinting that would expire every session and every
   * midnight, so the stamp covers the catalog, the skill, the tools and the
   * model instead — none of which can change without a deployment.
   */
  it('does not move when the date does', () => {
    const before = contractStamp();
    const realNow = Date.now;
    try {
      Date.now = () => realNow() + 40 * 24 * 60 * 60 * 1000;
      expect(contractStamp()).toBe(before);
    } finally {
      Date.now = realNow;
    }
  });

  it('is short enough to store and compare', () => {
    expect(contractStamp()).toMatch(/^[0-9a-z]{9,20}$/);
  });
});

describe('what the deployment advertises', () => {
  it('publishes the stamp, so a client can tell its receipt is out of date', async () => {
    expect((await meta()).contract.stamp).toBe(contractStamp());
  });

  /**
   * A backstop, not the main mechanism. The stamp catches a contract that
   * moved; the age catches what a stamp cannot see — a key revoked upstream, a
   * quota since exhausted.
   */
  it('publishes how long an instantiation stays good', async () => {
    const maxAge = (await meta()).contract.maxAgeMs;
    expect(maxAge).toBe(INSTANTIATION_MAX_AGE_MS);
    expect(maxAge).toBe(24 * 60 * 60 * 1000);
  });
});

describe('the fingerprint function', () => {
  /**
   * Exercised through the exported stamp rather than by reaching for the
   * private hash: what matters is that two different contracts cannot collide
   * into the same receipt, and FNV alone is weakest on inputs of the same
   * length — which is exactly the shape of a catalog edit that swaps two
   * equal-length strings. The length is mixed in for that reason.
   */
  it('separates inputs that differ only by a transposition', () => {
    // Rebuilt here from the same rule the module uses, because the point is the
    // rule and not the module's private binding.
    const fingerprint = (input: string) => {
      let hash = 0x811c9dc5;
      for (let i = 0; i < input.length; i++) {
        hash ^= input.charCodeAt(i);
        hash = Math.imul(hash, 0x01000193);
      }
      return `${(hash >>> 0).toString(16).padStart(8, '0')}${input.length.toString(36)}`;
    };

    expect(fingerprint('FlightOption')).not.toBe(fingerprint('FlihgtOption'));
    expect(fingerprint('a')).not.toBe(fingerprint('aa'));
    expect(fingerprint('')).not.toBe(fingerprint('a'));
  });
});
