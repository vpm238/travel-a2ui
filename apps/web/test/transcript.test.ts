/**
 * What a press says in the traveller's own chat line.
 *
 * Not the action's context verbatim (`paths: ["/trip/origin", ...],
 * startDate: "2027-04-12T00:00:00Z"`). These pin the readable version, without teaching the client what a trip is:
 * the label comes from the surface, and values are formatted by shape.
 */

import { describe, expect, it } from 'vitest';

import type { SurfaceAction } from '../src/api.js';
import { describeForTranscript, readable, type ComponentLookup } from '../src/conversation.js';

/** A surface as the store holds it: components by id. */
function surface(...nodes: Array<Record<string, unknown>>): ComponentLookup {
  const byId = new Map(nodes.map((node) => [String(node['id']), node]));
  return (_surfaceId, id) => byId.get(id);
}

const commit: SurfaceAction = {
  name: 'commit_surface',
  surfaceId: 'inline-1',
  sourceComponentId: '__commit',
  context: {
    paths: ['/trip/origin', '/trip/startDate', '/trip/endDate'],
    origin: 'JFK',
    startDate: '2027-04-12T00:00:00Z',
    endDate: '2027-04-19',
    travelers: 2,
  },
  dataModel: {},
};

describe('a press in the transcript', () => {
  it('reads as what was pressed and what it carried, not as the wire', () => {
    const lookup = surface(
      { id: '__commit', component: 'Button', child: '__commit_label', action: {} },
      { id: '__commit_label', component: 'Text', text: 'Send' },
    );
    const line = describeForTranscript(commit, lookup);
    expect(line).toBe('Send — origin: JFK, start date: 12 Apr 2027, end date: 19 Apr 2027, travelers: 2');
    expect(line).not.toContain('/trip/');
    expect(line).not.toContain('T00:00');
    expect(line).not.toContain('"');
  });

  it('prefers the label an author wrote for the control', () => {
    const lookup = surface({
      id: 'fare-1',
      component: 'FlightCard',
      accessibility: { label: 'Iberia IB6250, 18:40 JFK to 08:15 next day MAD, $412' },
    });
    const line = describeForTranscript(
      {
        name: 'select_flight',
        surfaceId: 's',
        sourceComponentId: 'fare-1',
        context: { flight: 'IB6250', seats: 2 },
      },
      lookup,
    );
    // The flight number is already in the label, so it is not said twice.
    expect(line).toBe('Iberia IB6250, 18:40 JFK to 08:15 next day MAD, $412 — seats: 2');
  });

  it('finds the face of a button whose child is a row', () => {
    const lookup = surface(
      { id: 'go', component: 'Button', child: 'row' },
      { id: 'row', component: 'Row', children: ['icon', 'words'] },
      { id: 'icon', component: 'Icon', name: 'search' },
      { id: 'words', component: 'Text', text: { '@path': '/cta' } },
    );
    const line = describeForTranscript(
      {
        name: 'search',
        surfaceId: 's',
        sourceComponentId: 'go',
        context: {},
        dataModel: { cta: 'Find flights' },
      },
      lookup,
    );
    expect(line).toBe('Find flights');
  });

  it('falls back to the action, in words, when nothing names the control', () => {
    expect(describeForTranscript(commit)).toBe(
      'Commit surface — origin: JFK, start date: 12 Apr 2027, end date: 19 Apr 2027, travelers: 2',
    );
  });

  it('survives a cycle in a malformed tree', () => {
    const lookup = surface(
      { id: 'a', component: 'Button', child: 'b' },
      { id: 'b', component: 'Row', children: ['a'] },
    );
    expect(
      describeForTranscript({ name: 'go', surfaceId: 's', sourceComponentId: 'a', context: {} }, lookup),
    ).toBe('Go');
  });
});

describe('values, by shape', () => {
  it('reads a calendar date without moving it by the viewer offset', () => {
    expect(readable('2027-01-01')).toBe('1 Jan 2027');
    expect(readable('2027-12-31T00:00:00Z')).toBe('31 Dec 2027');
    expect(readable('2027-12-31T18:40:00+01:00')).toBe('31 Dec 2027, 18:40');
  });

  it('drops plumbing and keeps answers', () => {
    expect(readable('/trip/origin')).toBeUndefined();
    expect(readable(['/a', '/b'])).toBeUndefined();
    expect(readable('')).toBeUndefined();
    expect(readable(null)).toBeUndefined();
    expect(readable(['JFK', 'EWR'])).toBe('JFK, EWR');
    expect(readable(true)).toBe('yes');
    expect(readable(0)).toBe('0');
  });
});
