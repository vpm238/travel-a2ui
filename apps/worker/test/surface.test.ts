/**
 * The server putting trip state into surfaces.
 *
 * This is the code that replaced `seedTrip` and `syncTrip` in the browser, so
 * what these assert is really one claim: a client that does nothing but apply
 * A2UI messages ends up with the same screen the React app used to build for
 * itself.
 */

import { describe, expect, it } from 'vitest';

const { seedSurfaceTrip, tripUpdates, planRows, STANDING_SURFACES } = await import(
  '../src/surface.js'
);

const createSurface = (dataModel?: Record<string, unknown>): any[] => [
  {
    version: 'v0.9.1' as const,
    createSurface: {
      surfaceId: 'inline-1',
      catalogId: 'a2ui-travel',
      components: [],
      ...(dataModel ? { dataModel } : {}),
    },
  },
];

const modelOf = (messages: any[]) => messages[0].createSurface.dataModel;

describe('seeding a surface', () => {
  it('fills /trip from what is already decided', () => {
    const seeded = seedSurfaceTrip(createSurface(), {
      origin: 'SFO',
      destination: 'Madrid',
      travelers: 2,
    } as never);
    expect(modelOf(seeded).trip).toMatchObject({
      origin: 'SFO',
      destination: 'Madrid',
      travelers: 2,
    });
  });

  it('lets the model propose a change to a fact already on file', () => {
    // A date the agent deliberately wrote is a proposal, and beats the older
    // fact it is proposing to replace.
    const seeded = seedSurfaceTrip(createSurface({ trip: { startDate: '2027-05-01' } }), {
      startDate: '2027-04-10',
      origin: 'SFO',
    } as never);
    expect(modelOf(seeded).trip.startDate).toBe('2027-05-01');
    expect(modelOf(seeded).trip.origin).toBe('SFO');
  });

  it('seeds the plan even when nothing is decided yet', () => {
    // Otherwise a panel drawn on turn one binds to nothing and renders blank.
    const seeded = seedSurfaceTrip(createSurface(), {} as never);
    expect(modelOf(seeded).plan.steps.length).toBeGreaterThan(0);
    expect(modelOf(seeded).plan.done).toBe(0);
  });

  it('leaves anything that is not a createSurface alone', () => {
    const messages = [
      { version: 'v0.9.1' as const, updateComponents: { surfaceId: 'inline-1', components: [] } },
    ];
    expect(seedSurfaceTrip(messages as never, { origin: 'SFO' } as never)).toEqual(messages);
  });
});

describe('updating a standing surface', () => {
  it('sends each fact as an updateDataModel a renderer already applies', () => {
    const updates = tripUpdates('sidebar', { origin: 'SFO', destination: 'Madrid' } as never);
    const paths = updates.map((m: any) => m.updateDataModel.path);
    expect(paths).toContain('/trip/origin');
    expect(paths).toContain('/trip/destination');
    expect(updates.every((m: any) => m.updateDataModel.surfaceId === 'sidebar')).toBe(true);
  });

  it('always carries the plan, so the checklist moves without a model turn', () => {
    const updates = tripUpdates('sidebar', {} as never);
    const plan = updates.find((m: any) => m.updateDataModel.path === '/plan') as any;
    expect(plan).toBeDefined();
    expect(plan.updateDataModel.value.steps.length).toBeGreaterThan(0);
  });

  it('updates the panels and never a spent inline card', () => {
    expect(STANDING_SURFACES).toEqual(['sidebar', 'home']);
  });
});

describe('the plan, as rows', () => {
  it('composes a line per stage so a template row can be one component', () => {
    const rows = planRows({ destination: 'Madrid', origin: 'SFO' } as never);
    for (const step of rows.steps as any[]) {
      expect(typeof step.line).toBe('string');
      expect(step.line).toMatch(/^[✓–→·] /);
    }
  });

  it('counts what is done against what this trip actually needs', () => {
    const rows = planRows({ destination: 'Madrid' } as never) as any;
    expect(rows.caption).toBe(`${rows.done} of ${rows.total}`);
    expect(rows.total).toBeGreaterThan(0);
    expect(rows.complete).toBe(false);
  });

  it('marks a ruled-out stage as not needed rather than outstanding', () => {
    const rows = planRows({ destination: 'Madrid', skip: ['stay'] } as never) as any;
    const stay = rows.steps.find((step: any) => step.stage === 'stay');
    expect(stay.state).toBe('skipped');
    expect(stay.line).toContain('not needed');
  });

  it('names each stop, and says what is unusual about it', () => {
    const rows = planRows({
      destination: 'Chicago',
      origin: 'SFO',
      legs: [{ destination: 'New York', travelers: 2, purpose: 'wedding' }],
    } as never) as any;
    expect(rows.multiStop).toBe(true);
    const lines = rows.route.map((stop: any) => stop.line).join(' | ');
    expect(lines).toContain('Chicago');
    expect(lines).toContain('New York');
    expect(lines).toContain('wedding');
  });
});
