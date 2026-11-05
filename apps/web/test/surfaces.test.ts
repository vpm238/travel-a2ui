// @vitest-environment happy-dom
/**
 * The app's surfaces, held by `@a2ui/web_core`.
 *
 * The JavaScript twin of `apps/server/tests/test_surface_lifecycle.py`: a real
 * recorded conversation, every message in order, through the SDK processor the
 * browser renders with. Before the server made its stream conformant, this
 * processor rejected 141 of these messages — among them the agent's real card
 * on every turn.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { Surfaces, type SurfacePress } from '../src/surfaces.js';

const sample = JSON.parse(readFileSync(join(__dirname, '..', 'public', 'sample-trip.json'), 'utf8')) as {
  turns: Array<{ events: Array<{ type: string; messages?: unknown[] }> }>;
};

const CATALOG = 'https://travel-a2ui.dev/catalogs/a2ui-travel/catalog.json';

describe('a whole recorded conversation', () => {
  const surfaces = new Surfaces();
  for (const turn of sample.turns) {
    for (const event of turn.events) if (event.type === 'ui' && event.messages) surfaces.apply(event.messages);
  }

  it('is accepted, every message of it', () => {
    expect(surfaces.rejected).toEqual([]);
  });

  it('draws every card and the panel', () => {
    expect(surfaces.ids()).toContain('sidebar');
    // Every inline card the recording creates; a turn may draw only into the
    // panel, so this is counted from the messages, not from the turns.
    const created = new Set<string>();
    for (const turn of sample.turns) {
      for (const event of turn.events) {
        for (const message of (event.messages ?? []) as Array<{ createSurface?: { surfaceId?: string } }>) {
          const id = message.createSurface?.surfaceId;
          if (id?.startsWith('sample-inline-')) created.add(id);
        }
      }
    }
    expect(created.size).toBeGreaterThan(0);
    expect(surfaces.ids().filter((id) => id.startsWith('sample-inline-')).sort()).toEqual([...created].sort());
    expect(surfaces.has('sidebar')).toBe(true);
  });

  it("keeps the lookup's rows when the agent's card replaces the placeholder", () => {
    const flights = surfaces.data('sample-inline-1')['flights'];
    expect(Array.isArray(flights) && flights.length > 0).toBe(true);
    expect((flights as Array<Record<string, unknown>>)[0]!['airline']).toBeTruthy();
  });
});

describe('the adapter', () => {
  const surfaces = new Surfaces();
  surfaces.apply([
    {
      version: '1.0',
      createSurface: {
        surfaceId: 'inline-1',
        catalogId: CATALOG,
        components: [
          { id: 'root', component: 'Column', children: ['face', 'go'] },
          { id: 'face', component: 'Text', text: 'Send' },
          {
            id: 'go',
            component: 'Button',
            child: 'face',
            action: { event: { name: 'commit_surface', context: { origin: 'JFK' } } },
          },
        ],
        dataModel: { trip: { origin: 'JFK', travelers: 2 } },
        sendDataModel: true,
      },
    },
    {
      version: '1.0',
      createSurface: {
        surfaceId: 'inline-2',
        catalogId: CATALOG,
        components: [
          { id: 'root', component: 'Column', children: ['go'] },
          { id: 'face', component: 'Text', text: 'Go' },
          { id: 'go', component: 'Button', child: 'face', action: { event: { name: 'go' } } },
        ],
        dataModel: { secret: 'not asked for' },
      },
    },
  ]);

  it("reads a component as the agent wrote it, for naming a press", () => {
    expect(surfaces.component('inline-1', 'face')).toMatchObject({ component: 'Text', text: 'Send' });
  });

  it('reads the data model as a plain object', () => {
    expect(surfaces.data('inline-1')).toEqual({ trip: { origin: 'JFK', travelers: 2 } });
  });

  it('snapshots a surface as one createSurface for the Wire view', () => {
    const snapshot = surfaces.snapshot('inline-1')!;
    expect(snapshot['catalogId']).toBe(CATALOG);
    expect((snapshot['components'] as unknown[]).length).toBe(3);
    expect(surfaces.get('inline-1')!.sendDataModel).toBe(true);
  });

  it('forwards a press with the surface it came from and its values', async () => {
    let pressed: SurfacePress | null = null;
    surfaces.onPress((press) => (pressed = press));
    await surfaces
      .get('inline-1')!
      .dispatchAction({ event: { name: 'commit_surface', context: { origin: 'JFK' } } }, 'go');
    expect(pressed).toMatchObject({
      name: 'commit_surface',
      surfaceId: 'inline-1',
      sourceComponentId: 'go',
      context: { origin: 'JFK' },
      dataModel: { trip: { origin: 'JFK', travelers: 2 } },
    });
  });

  it('sends the values only when the surface asked for them (sendDataModel)', async () => {
    let pressed: SurfacePress | null = null;
    surfaces.onPress((press) => (pressed = press));
    await surfaces.get('inline-2')!.dispatchAction({ event: { name: 'go' } }, 'go');
    expect(pressed!.dataModel).toEqual({});
  });

  it('keeps a refused message for the Wire view instead of throwing', () => {
    const before = surfaces.rejected.length;
    surfaces.apply([{ version: '1.0', updateDataModel: { surfaceId: 'nowhere', path: '/a', value: 1 } }]);
    expect(surfaces.rejected.length).toBe(before + 1);
  });
});
