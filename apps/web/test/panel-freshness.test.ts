/**
 * Telling a panel that was redrawn from one that was merely refreshed.
 *
 * The client keeps two fingerprints — the shape of the trip's decisions, and
 * the shape the panel on screen was drawn for — and asks for the panel itself
 * when they disagree. That catch-up exists because the server rebuilds panels
 * in the tail of a turn, which is exactly when a traveller presses the fare
 * they have just been shown and cancels it.
 *
 * It had never once fired. The client marked the panel current on *any* event
 * for a standing surface, and the host sends one of those at the end of every
 * turn: `panel_events`, which pushes the trip's values into the panels as
 * `updateDataModel` and draws nothing. So the two shapes could not disagree,
 * and when a panel genuinely failed to draw on the deployed app the sidebar sat
 * there reading "Stay in Berlin · Awaiting selection" with the stay booked.
 *
 * One predicate fixes it, and this is that predicate.
 */

import { describe, expect, it } from 'vitest';

import { redrawsSurface } from '../src/conversation.js';

/** What `panel_events` sends at the end of every turn: values, no components. */
const refresh = [
  {
    version: 'v0.9.1',
    updateDataModel: { surfaceId: 'sidebar', path: '/trip/origin', value: 'CPH' },
  },
  {
    version: 'v0.9.1',
    updateDataModel: { surfaceId: 'sidebar', path: '/plan', value: [] },
  },
];

/** What a rebuilt panel sends: the surface, and what is in it. */
const redraw = [
  { version: 'v0.9.1', createSurface: { surfaceId: 'sidebar', catalogId: 'catalog.json' } },
  {
    version: 'v0.9.1',
    updateComponents: {
      surfaceId: 'sidebar',
      components: [{ id: 'root', component: 'Column', children: [] }],
    },
  },
];

describe('redrawsSurface', () => {
  it('is false for a value refresh, whatever it touches', () => {
    expect(redrawsSurface(refresh)).toBe(false);
  });

  it('is true when the surface is drawn', () => {
    expect(redrawsSurface(redraw)).toBe(true);
  });

  it('is true when a redraw arrives with a refresh beside it', () => {
    expect(redrawsSurface([...refresh, ...redraw])).toBe(true);
  });

  it('is false for nothing at all', () => {
    expect(redrawsSurface([])).toBe(false);
  });

  it('survives whatever else arrives on the wire', () => {
    expect(redrawsSurface([null, undefined, 'text', 7, { version: 'v0.9.1' }])).toBe(false);
  });
});
