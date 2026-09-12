/**
 * The two agent frameworks, as the front end learns about them.
 *
 * The microphone used to sit in the composer at all times, and pressing it
 * quietly opened a second runtime on a different API with its own conversation
 * history. That made two frameworks look like one app with a feature. The
 * traveller chooses now, and the front end branches on `voice` — so this
 * asserts the field exists, is honest about which one listens, and that both
 * are reachable.
 */

import { describe, expect, it } from 'vitest';

import worker from '../src/index.js';

const env = { ASSETS: undefined, TRIP_SESSION: undefined } as never;

async function meta() {
  const response = await worker.fetch(new Request('https://example.test/api/meta'), env, {} as never);
  return (await response.json()) as any;
}

describe('the frameworks a traveller can choose', () => {
  it('offers both, not a picker over a list of one', async () => {
    const ids = (await meta()).backends.map((entry: any) => entry.id);
    expect(ids).toEqual(['worker', 'live']);
  });

  it('says which one listens, because the microphone follows that', async () => {
    const byId = Object.fromEntries((await meta()).backends.map((e: any) => [e.id, e]));
    expect(byId['worker'].voice).toBe(false);
    expect(byId['live'].voice).toBe(true);
  });

  it('names the API each one actually runs on', async () => {
    const byId = Object.fromEntries((await meta()).backends.map((e: any) => [e.id, e]));
    expect(byId['worker'].note).toContain('Interactions API');
    expect(byId['live'].note).toContain('Live API');
  });

  it('gives every framework a label and a note worth reading', async () => {
    for (const entry of (await meta()).backends) {
      expect(entry.label, entry.id).toBeTruthy();
      expect(entry.note.length, entry.id).toBeGreaterThan(40);
    }
  });
});
