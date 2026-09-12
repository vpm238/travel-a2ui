/**
 * The agent loop, against a scripted Gemini stream.
 *
 * `fetch` is replaced by a fake that replays a canned SSE body in the
 * Interactions API's own shape — `interaction.created`, `step.delta`,
 * `step.stop`, `interaction.completed`. That makes the interesting things
 * testable without spending a token or depending on a model behaving the same
 * way twice, and unlike mocking a client object it exercises the real wire
 * parsing: an event shape we read wrongly fails here rather than in production.
 *
 * What is deliberately not mocked is the Express compiler — the whole risk in
 * this pipeline is between the model's text and the host's components, and a
 * mock there would test nothing.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { providerFor } from '../src/providers/index.js';

interface ScriptedTurn {
  /** Text chunks, delivered in order as `step.delta` text events. */
  chunks: string[];
  /** Tool calls this turn asks for. */
  calls?: Array<{ id?: string; name: string; args: Record<string, unknown> }>;
  status?: string;
  usage?: Partial<{ total_input_tokens: number; total_output_tokens: number }>;
}

const script: ScriptedTurn[] = [];
/** Every request body the agent sent, so tests can assert on what it asked. */
const requests: any[] = [];
let failWith: { status: number; body: string } | null = null;

/** One scripted turn as the SSE frames the API would actually send. */
function sseBody(turn: ScriptedTurn, index: number): string {
  const frames: unknown[] = [
    { event_type: 'interaction.created', interaction: { id: `int_${index}`, status: 'in_progress' } },
  ];

  for (const chunk of turn.chunks) {
    frames.push({ event_type: 'step.delta', index: 0, delta: { type: 'text', text: chunk } });
  }
  frames.push({
    event_type: 'step.stop',
    index: 0,
    step_usage: {
      total_input_tokens: 100,
      total_output_tokens: 50,
      ...turn.usage,
    },
  });

  // Each call is its own step, with its arguments streamed as partial JSON —
  // the shape that only parses once the step stops.
  turn.calls?.forEach((call, position) => {
    const at = position + 1;
    const args = JSON.stringify(call.args);
    frames.push({
      event_type: 'step.start',
      index: at,
      step: { type: 'function_call', id: call.id ?? `call_${at}`, name: call.name },
    });
    frames.push({
      event_type: 'step.delta',
      index: at,
      delta: { type: 'arguments_delta', arguments: args.slice(0, 3) },
    });
    frames.push({
      event_type: 'step.delta',
      index: at,
      delta: { type: 'arguments_delta', arguments: args.slice(3) },
    });
    frames.push({ event_type: 'step.stop', index: at, step_usage: {} });
  });

  frames.push({
    event_type: 'interaction.completed',
    interaction: { id: `int_${index}`, status: turn.status ?? 'completed' },
  });

  return frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join('');
}

let turnIndex = 0;

vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => {
  requests.push(JSON.parse(String(init.body ?? '{}')));
  if (failWith) {
    return new Response(failWith.body, { status: failWith.status });
  }
  const turn = script.shift() ?? { chunks: [''] };
  return new Response(sseBody(turn, turnIndex++), {
    status: 200,
    headers: { 'content-type': 'text/event-stream' },
  });
});


const { runTurn } = await import('../src/agent.js');
const { buildSystemPrompt, describeAllSkills, describeSkill } = await import('../src/skills.js');
const { runTool } = await import('../src/tools.js');
const { originForTimeZone } = await import('../src/travel.js');

function baseRequest(overrides: Record<string, unknown> = {}) {
  return {
    apiKey: 'test-gemini-key',
    model: 'gemini-3.8-flash',
    message: 'Six days in Madrid',
    interactionId: null,
    trip: {},
    surface: 'inline' as const,
    surfaceId: 'inline-1',
    skill: 'express-monolithic' as const,
    effort: 'medium' as const,
    ...overrides,
  };
}

/** The text of the user turn in the nth request the agent sent. */
function sentText(index = 0): string {
  return (requests[index]?.input ?? [])
    .flatMap((entry: any) => entry.content ?? [])
    .map((part: any) => part.text ?? '')
    .join('');
}

async function collect(request = baseRequest()) {
  const events: any[] = [];
  const result = await runTurn(request as any, (event) => events.push(event));
  return { events, result };
}

beforeEach(() => {
  script.length = 0;
  requests.length = 0;
  failWith = null;
  turnIndex = 0;
});

describe('prose and UI', () => {
  it('keeps prose out of the surface and the surface out of the prose', async () => {
    script.push({
      chunks: [
        'Three options for you.\n',
        '<a2ui>\nh = Text("Flights", variant="h3")\n',
        'root = Column([h])\n</a2ui>\n',
        'Want me to hold one?',
      ],
    });

    const { events } = await collect();
    const text = events.filter((e) => e.type === 'text').map((e) => e.delta).join('');
    expect(text).toContain('Three options for you.');
    expect(text).toContain('Want me to hold one?');
    expect(text).not.toContain('Column');

    // Scoped to the surface this turn drew: the panels also get `ui` events at
    // the end of a turn, carrying `updateDataModel` rather than components.
    const done = events.filter((e) => e.type === 'ui' && e.done && e.surfaceId === 'inline-1');
    expect(done).toHaveLength(1);
    const components = done[0].messages.flatMap((message: any) =>
      message.updateComponents ? message.updateComponents.components : [],
    );
    expect(components.map((c: any) => c.id)).toEqual(['h', 'root']);
  });

  it('paints the surface before the block is closed', async () => {
    script.push({
      chunks: ['<a2ui>\na = Text("One")\nroot = Column([a])\n', 'b = Text("Two")\n', '</a2ui>'],
    });

    const { events } = await collect();
    const partial = events.filter((e) => e.type === 'ui' && !e.done);
    expect(partial.length).toBeGreaterThan(0);
  });

  it('draws into the surface it was told to draw into', async () => {
    script.push({ chunks: ['<a2ui>\nroot = Text("Hi")\n</a2ui>'] });
    const { events } = await collect(baseRequest({ surfaceId: 'sidebar', surface: 'sidebar' }));
    const ui = events.find((e) => e.type === 'ui' && e.done);
    expect(ui.messages[0].createSurface.surfaceId).toBe('sidebar');
  });

  it('reports a surface that does not compile without killing the turn', async () => {
    script.push({ chunks: ['<a2ui>\nroot = Column([\n</a2ui>'] });
    const { events } = await collect();
    expect(events.some((e) => e.type === 'ui_error')).toBe(true);
    expect(events.some((e) => e.type === 'done')).toBe(true);
  });
});

/**
 * The rules that stop the agent making things up.
 *
 * These live in the tools rather than in the prompt because a prompt rule is
 * advice: a model that wants to be helpful prices a plausible week, calls it a
 * sample, and the traveler is looking at fares for a date they never chose.
 * Here it cannot get numbers without asking first.
 */
describe('inputs the traveler has to give', () => {
  const run = (name: string, input: Record<string, unknown>, trip: Record<string, unknown> = {}) => {
    const context = {
      trip,
      saveTrip: (patch: Record<string, unknown>) => Object.assign(trip, patch),
      provider: providerFor(undefined),
    };
    return runTool(name, input, context);
  };

  it('names exactly what it is missing rather than refusing vaguely', async () => {
    const { result } = await run('search_flights', { destination: 'Madrid' });
    expect((result as any).needs).toEqual(['origin', 'startDate']);
    expect((result as any).flights).toBeUndefined();
    // Addressed to a model that has to fix it, so it names the binding paths.
    expect((result as any).message).toMatch(/\$\/trip\/origin/);
    expect((result as any).message).toMatch(/\$\/trip\/startDate/);
  });

  /**
   * The multi-stop case, which is where this silently went wrong.
   *
   * A trip's flat fields describe the *first* stop. Pricing a later one against
   * them used the outbound party size, the outbound dates and the original
   * departure airport — and returned a confident number for a journey nobody
   * was taking.
   */
  describe('pricing a stop that is not the first', () => {
    const wedding = {
      origin: 'SFO',
      destination: 'Chicago',
      startDate: '2027-04-10',
      endDate: '2027-04-12',
      travelers: 1,
      legs: [
        { destination: 'New York', startDate: '2027-04-12', endDate: '2027-04-16' },
        { destination: 'SFO', startDate: '2027-04-16', travelers: 2 },
      ],
    };

    it('counts the people on that leg, not the people on the first', async () => {
      const { result } = await run('search_flights', { destination: 'SFO' }, { ...wedding });
      expect((result as any).searchedFor.travelers).toBe(2);
    });

    it('departs from the stop before it, not from the original origin', async () => {
      const { result } = await run('search_flights', { destination: 'SFO' }, { ...wedding });
      expect((result as any).searchedFor.origin).toBe('New York');
    });

    it('prices it on that leg\'s dates', async () => {
      const { result } = await run('search_flights', { destination: 'New York' }, { ...wedding });
      expect((result as any).searchedFor.date).toBe('2027-04-12');
    });

    it('still lets the call override the leg', async () => {
      const { result } = await run(
        'search_flights',
        { destination: 'SFO', travelers: 4 },
        { ...wedding },
      );
      expect((result as any).searchedFor.travelers).toBe(4);
    });

    it('leaves a single-stop trip exactly as it was', async () => {
      const { result } = await run(
        'search_flights',
        { destination: 'Madrid' },
        { origin: 'LHR', destination: 'Madrid', startDate: '2027-04-12', travelers: 3 },
      );
      expect((result as any).searchedFor.travelers).toBe(3);
      expect((result as any).searchedFor.origin).toBe('LHR');
    });
  });

  it('uses what is already saved without being handed it again', async () => {
    const { result } = await run(
      'search_flights',
      { destination: 'Madrid' },
      { origin: 'LHR', startDate: '2026-04-12', travelers: 2 },
    );
    expect((result as any).flights.length).toBeGreaterThan(0);
    expect((result as any).searchedFor.date).toBe('2026-04-12');
    expect((result as any).searchedFor.origin).toBe('LHR');
    expect((result as any).searchedFor.travelers).toBe(2);
    expect((result as any).searchedFor.indicative).toBe(false);
    expect((result as any).searchedFor.basis).toBe('LHR → Madrid · from 12 Apr · 2 travellers');
  });

  it('answers a deliberately rough question, and marks it as rough', async () => {
    const { result } = await run('search_flights', { destination: 'Madrid', flexible: true });
    expect((result as any).flights.length).toBeGreaterThan(0);
    expect((result as any).searchedFor.indicative).toBe(true);
  });

  it('will not total a trip whose length it does not know', async () => {
    const { result } = await run('estimate_cost', { destination: 'Madrid' });
    expect((result as any).needs).toEqual(['startDate', 'endDate', 'travelers']);
    expect((result as any).total).toBeUndefined();
  });

  it('totals against the saved range and says what it assumed', async () => {
    const { result } = await run(
      'estimate_cost',
      { destination: 'Madrid' },
      { startDate: '2026-04-12', endDate: '2026-04-19', travelers: 2 },
    );
    expect((result as any).total).toMatch(/^\$/);
    expect((result as any).basis).toEqual({
      summary: 'Madrid · 12–19 Apr · 2 travellers',
      nights: 7,
      travelers: 2,
      startDate: '2026-04-12',
      endDate: '2026-04-19',
      indicative: false,
    });
  });

  it('refuses to record a date range that ends before it starts', async () => {
    const trip: Record<string, unknown> = {};
    const { result, isError } = await run(
      'save_trip',
      { startDate: '2026-04-19', endDate: '2026-04-12' },
      trip,
    );
    expect(isError).toBe(true);
    expect((result as any).saved).toBe(false);
    expect(trip.startDate).toBeUndefined();
  });
});

describe('where the traveler is', () => {
  it('suggests a departure airport from a timezone it knows', () => {
    expect(originForTimeZone('Europe/Madrid')?.code).toBe('CDG');
    expect(originForTimeZone('Asia/Kolkata')?.code).toBe('DEL');
    expect(originForTimeZone('America/Los_Angeles')?.code).toBe('LAX');
  });

  // Better a hub on the right continent than a confident wrong hemisphere.
  it('falls back to the region rather than to New York', () => {
    expect(originForTimeZone('Europe/Warsaw')?.code).toBe('LHR');
    expect(originForTimeZone('Asia/Ulaanbaatar')?.code).toBe('DXB');
  });

  it('suggests nothing when it knows nothing', () => {
    expect(originForTimeZone(undefined)).toBeUndefined();
    expect(originForTimeZone('Mars/Olympus_Mons')).toBeUndefined();
  });
});

describe('tools', () => {
  it('runs a tool and sends every result back in one message', async () => {
    script.push({
      chunks: [''],
      calls: [
        { id: 't1', name: 'search_flights', args: { destination: 'Madrid' } },
        { id: 't2', name: 'get_weather', args: { destination: 'Madrid' } },
      ],
    });
    script.push({ chunks: ['Here you go.'] });

    const { events, result } = await collect();
    expect(events.filter((e) => e.type === 'tool')).toHaveLength(2);
    expect(events.filter((e) => e.type === 'tool_result')).toHaveLength(2);

    // Every result from one round goes back in the *next* request, together,
    // or the model learns to stop calling tools in parallel.
    const sent = requests[1].input.filter((entry: any) => entry.type === 'function_result');
    expect(sent).toHaveLength(2);
    expect(sent.map((entry: any) => entry.name).sort()).toEqual(['get_weather', 'search_flights']);
    expect(result.interactionId).toBe('int_1');
  });

  it('chains each turn to the one before it, instead of resending the history', async () => {
    script.push({ chunks: [''], calls: [{ name: 'get_trip', args: {} }] });
    script.push({ chunks: ['Done.'] });
    await collect();

    // The first request opens a chain; the second continues it.
    expect(requests[0].previous_interaction_id).toBeUndefined();
    expect(requests[1].previous_interaction_id).toBe('int_0');
    // And carries only the results, not the conversation.
    expect(requests[1].input.every((entry: any) => entry.type === 'function_result')).toBe(true);
  });

  it('continues an existing conversation when given its id', async () => {
    script.push({ chunks: ['ok'] });
    await collect(baseRequest({ interactionId: 'int_earlier' }));
    expect(requests[0].previous_interaction_id).toBe('int_earlier');
  });

  it('remembers what save_trip recorded', async () => {
    script.push({
      chunks: [''],
      calls: [{ id: 't1', name: 'save_trip', args: { destination: 'Madrid', travelers: 2 } }],
    });
    script.push({ chunks: ['Saved.'] });

    const { result } = await collect();
    expect(result.trip).toEqual({ destination: 'Madrid', travelers: 2 });
  });

  it('reports a failing tool without ending the turn', async () => {
    script.push({
      chunks: [''],
      calls: [{ id: 't1', name: 'not_a_tool', args: {} }],
    });
    script.push({ chunks: ['Sorry about that.'] });

    const { events } = await collect();
    const failure = events.find((e) => e.type === 'tool_result' && e.isError);
    expect(failure).toBeTruthy();
    expect(events.some((e) => e.type === 'done')).toBe(true);
  });

  it('stops after a bounded number of tool rounds', async () => {
    for (let index = 0; index < 10; index++) {
      script.push({
        chunks: [''],
        calls: [{ id: `t${index}`, name: 'get_trip', args: {} }],
      });
    }

    const { events } = await collect();
    const stopped = events.find((e) => e.type === 'error' && /rounds of tool calls/.test(e.message));
    expect(stopped).toBeTruthy();
  });
});

describe('the request the model receives', () => {
  it('carries the skill, stable half first so a repeated prefix can be cached', async () => {
    script.push({ chunks: ['ok'] });
    await collect();

    const [request] = requests;
    const prompt: string = request.system_instruction;
    expect(prompt).toContain('A2UI Express DSL Output Contract');
    expect(prompt).toContain('inline-1');

    // Order is the optimisation: Gemini caches a repeated prefix implicitly, so
    // the catalog and the rules — identical on every turn — must come before
    // anything that changes per turn, or nothing is a prefix.
    expect(prompt.indexOf('A2UI Express DSL Output Contract')).toBeLessThan(
      prompt.indexOf('inline-1'),
    );
  });

  it('sends the tools and the model that were asked for', async () => {
    script.push({ chunks: ['ok'] });
    await collect(baseRequest({ model: 'gemini-3.7-flash' }));

    const [request] = requests;
    expect(request.model).toBe('gemini-3.7-flash');
    expect(request.stream).toBe(true);
    expect(request.tools.map((tool: any) => tool.name)).toContain('search_flights');
    // Gemini wants `parameters`, not Anthropic's `input_schema`.
    expect(request.tools.every((tool: any) => tool.type === 'function' && tool.parameters)).toBe(true);
  });

  it('turns a pressed action into the user turn', async () => {
    script.push({ chunks: ['ok'] });
    await collect(
      baseRequest({
        message: '',
        action: {
          name: 'search_flights',
          surfaceId: 'inline-1',
          sourceComponentId: 'go',
          context: { origin: 'SFO', maxPrice: 600 },
        },
      }),
    );

    const content = sentText();
    expect(content).toContain('search_flights');
    expect(content).toContain('maxPrice');
    expect(content).toContain('SFO');
  });

  it('takes trip facts from the action context', async () => {
    script.push({ chunks: ['ok'] });
    const { events } = await collect(
      baseRequest({
        message: '',
        action: {
          name: 'commit',
          surfaceId: 'inline-1',
          context: { origin: 'SFO', destination: 'NYC' },
        },
      }),
    );

    const trip = events.filter((event) => event.type === 'trip').at(-1) as any;
    expect(trip.trip.origin).toBe('SFO');
    expect(trip.trip.destination).toBe('NYC');
  });

  it('prefers the context over the rest of the surface', async () => {
    script.push({ chunks: ['ok'] });
    const { events } = await collect(
      baseRequest({
        message: '',
        action: {
          name: 'commit',
          surfaceId: 'inline-1',
          // The button declared it was sending JFK; the data model still holds
          // a stale SFO from before the traveler changed it.
          context: { origin: 'JFK' },
          dataModel: { trip: { origin: 'SFO', destination: 'NYC' } },
        },
      }),
    );

    const trip = events.filter((event) => event.type === 'trip').at(-1) as any;
    expect(trip.trip.origin).toBe('JFK');
    // ...and a field no binding named still survives.
    expect(trip.trip.destination).toBe('NYC');
  });

  it('lets typing win when both arrive, and still banks the values', async () => {
    // Someone can type while a surface is on screen. What they said is the
    // turn; what the surface held still reaches the trip.
    script.push({ chunks: ['ok'] });
    const { events } = await collect(
      baseRequest({
        message: 'actually make it Lisbon',
        action: {
          name: 'commit',
          surfaceId: 'inline-1',
          context: { origin: 'SFO' },
        },
      }),
    );

    expect(sentText()).toBe('actually make it Lisbon');
    const trip = events.filter((event) => event.type === 'trip').at(-1) as any;
    expect(trip.trip.origin).toBe('SFO');
  });

  it('reads a panel press as a request to re-open the decision', async () => {
    script.push({ chunks: ['ok'] });
    await collect(
      baseRequest({
        message: '',
        surface: 'sidebar',
        action: { name: 'change', surfaceId: 'sidebar', context: { field: 'startDate' } },
      }),
    );

    const content = sentText();
    expect(content).toContain('startDate');
    expect(content).toMatch(/release/i);
    expect(content).toMatch(/inline/i);
  });
});

describe('failures', () => {
  it('explains a rejected key in words the user can act on', async () => {
    failWith = { status: 401, body: JSON.stringify({ error: { message: 'bad key' } }) };
    script.push({ chunks: [''] });

    const { events } = await collect();
    const error = events.find((e) => e.type === 'error');
    expect(error.message).toMatch(/rejected/i);
    expect(error.retryable).toBe(false);
  });

  it('reports the interaction status it ended on', async () => {
    script.push({ chunks: [''], status: 'completed' });
    const { result } = await collect();
    expect(result.stopReason).toBe('completed');
  });

  it('says a rate limit is worth retrying and a bad key is not', async () => {
    failWith = { status: 429, body: '{}' };
    script.push({ chunks: [''] });
    const { events } = await collect();
    const error = events.find((e) => e.type === 'error');
    expect(error.retryable).toBe(true);
  });

  /**
   * Express that does not compile used to end the turn with a broken surface
   * and the model none the wiser — it had written something wrong and nothing
   * ever told it. This is a live failure the eval suite caught: the model wrote
   * `duration: "2h"` where the grammar wants `duration="2h"`.
   */
  describe('a block that does not compile', () => {
    const BROKEN = 'root = Text("Madrid", variant: "h3")';
    const FIXED = 'root = Text("Madrid", variant="h3")';

    it('hands the error back and takes the corrected block', async () => {
      script.push({ chunks: [`Here you go.\n<a2ui>\n${BROKEN}\n</a2ui>\n`] });
      script.push({ chunks: [`<a2ui>\n${FIXED}\n</a2ui>\n`] });

      const { events, result } = await collect();

      expect(events.some((e) => e.type === 'ui_error')).toBe(true);
      expect(events.some((e) => e.type === 'retry')).toBe(true);

      // What it was told: the reason, and the block it wrote.
      const correction = requests[1].input
        .flatMap((entry: any) => entry.content ?? [])
        .map((part: any) => part.text)
        .join('');
      expect(correction).toContain('did not compile');
      expect(correction).toContain("keyword arguments use '='");
      expect(correction).toContain(BROKEN);

      // And the second attempt drew.
      const drawn = events.filter((e) => e.type === 'ui' && e.done);
      expect(drawn.length).toBeGreaterThan(0);
    });

    it('says which mistake it was, not just where', async () => {
      script.push({ chunks: [`<a2ui>\n${BROKEN}\n</a2ui>\n`] });
      script.push({ chunks: ['Sorry.'] });

      const { events } = await collect();
      const failure = events.find((e) => e.type === 'ui_error');
      expect(failure.message).toMatch(/keyword arguments use '=', not ':'/);
      expect(failure.express).toContain('variant:');
    });

    // A model that cannot fix it on the second attempt will not fix it on the
    // fifth, and the traveler is waiting.
    it('retries once, not forever', async () => {
      for (let attempt = 0; attempt < 4; attempt++) {
        script.push({ chunks: [`<a2ui>\n${BROKEN}\n</a2ui>\n`] });
      }

      const { events } = await collect();
      expect(events.filter((e) => e.type === 'retry')).toHaveLength(1);
    });
  });
});

describe('skills', () => {
  it('describes each variant by what it loads, not by its file path', () => {
    const variants = describeAllSkills();
    expect(variants.map((entry) => entry.skills)).toEqual([
      ['a2ui'],
      ['a2ui-core', 'a2ui-travel'],
      ['a2ui'],
    ]);
  });

  it('gives the modular pair the same components as the monolith', () => {
    const mono = describeSkill('express-monolithic');
    const modular = describeSkill('express-modular');
    expect(modular.characters).toBeGreaterThan(mono.characters * 0.9);
  });

  it('strips frontmatter before the model sees the skill', () => {
    const prompt = buildSystemPrompt({
      variant: 'express-monolithic',
      surface: 'inline',
      surfaceId: 'inline-1',
      catalogId: 'https://example.test/catalog.json',
      trip: {},
      today: '2026-04-01',
    });
    expect(prompt.startsWith('---')).toBe(false);
    expect(prompt).not.toContain('protocol_version:');
  });

  it('gives each surface a different brief', () => {
    const brief = (surface: 'inline' | 'sidebar' | 'home') =>
      buildSystemPrompt({
        variant: 'express-monolithic',
        surface,
        surfaceId: surface,
        catalogId: 'c',
        trip: {},
        today: '2026-04-01',
      });

    expect(brief('inline')).toContain('inline, in the conversation');
    expect(brief('home')).toContain('home screen');

    // The panel is read-only, and the brief has to say so in a way the model
    // cannot read past — it is the one surface where drawing a control would
    // produce something that visibly does nothing.
    const panel = brief('sidebar');
    expect(panel).toContain('read-only');
    expect(panel).toContain('No editors here');
    expect(panel).toContain('Change');
  });

  /**
   * The eval caught this: told to lead the trip *and* that the panel is
   * read-only, the model advanced the plan in the panel, with the controls the
   * next step needed. Both instructions were reasonable; together they were
   * contradictory, and a model resolves a contradiction by picking one.
   */
  it('does not ask an inline turn and a panel turn to do the same job', () => {
    const forSurface = (surface: 'inline' | 'sidebar' | 'home') =>
      buildSystemPrompt({
        variant: 'express-monolithic',
        surface,
        surfaceId: surface,
        catalogId: 'c',
        trip: { destination: 'Madrid', origin: 'LHR', startDate: '2027-04-12', endDate: '2027-04-19' },
        today: '2026-09-03',
      });

    expect(forSurface('inline')).toContain('**Do this next.**');
    for (const panel of ['sidebar', 'home'] as const) {
      expect(forSurface(panel)).toContain('**Not this turn.**');
      expect(forSurface(panel)).not.toContain('**Do this next.**');
      expect(forSurface(panel)).toContain('Ask for nothing');
    }
  });

  const promptFor = (
    trip: Record<string, unknown>,
    extra: Partial<Parameters<typeof buildSystemPrompt>[0]> = {},
  ) =>
    buildSystemPrompt({
      variant: 'express-monolithic',
      surface: 'inline',
      surfaceId: 'i',
      catalogId: 'c',
      trip,
      today: '2026-04-01',
      ...extra,
    });

  it('tells the model when nothing is decided yet', () => {
    expect(promptFor({})).toContain('Nothing is settled yet');
  });

  // The whole reason this is spelled out rather than dumped as JSON: a model
  // asked to infer what is absent tends to fill the gap in itself, and the gap
  // it fills in is a departure date nobody chose.
  it('names the fields that are still missing, not just the ones that are set', () => {
    const prompt = promptFor({ destination: 'Madrid' });
    expect(prompt).toContain('destination="Madrid"');
    expect(prompt).toMatch(/Not yet known:.*startDate/);
    expect(prompt).toMatch(/Not yet known:.*travelers/);
    expect(prompt).not.toMatch(/Not yet known:.*destination/);
  });

  it('stops asking once everything is settled', () => {
    const prompt = promptFor({
      destination: 'Madrid',
      origin: 'JFK',
      startDate: '2026-04-12',
      endDate: '2026-04-19',
      travelers: 2,
      budget: 2600,
      cabin: 'economy',
      nonstopOnly: false,
      selectedFlight: 'IB6250',
      selectedHotel: 'h1',
    });
    expect(prompt).toContain('Everything needed is known');
    expect(prompt).not.toContain('Not yet known');
  });

  it('offers a departure airport as a suggestion, never as an answer', () => {
    const prompt = promptFor(
      { destination: 'Madrid' },
      { originHint: { code: 'LHR', city: 'London', timeZone: 'Europe/London' } },
    );
    expect(prompt).toContain('Europe/London');
    expect(prompt).toContain('London (LHR)');
    expect(prompt).toContain('suggestion');
    expect(prompt).toContain('Do not treat it as their answer');
  });

  it('says nothing about a departure airport once one is chosen', () => {
    const prompt = promptFor(
      { destination: 'Madrid', origin: 'CDG' },
      { originHint: { code: 'LHR', city: 'London', timeZone: 'Europe/London' } },
    );
    expect(prompt).not.toContain('LHR');
  });
});


/**
 * What a commit is allowed to change.
 *
 * `save_trip` has validated since the beginning, so a *model* that proposed a
 * return before the departure was refused. The other way a value arrives — the
 * traveler pressing a button — went straight into the trip unchecked, and a
 * live run found it: a picker sent 20 April → 12 April and the agent priced
 * four flights against a trip with negative nights.
 */
describe('committing a surface', () => {
  const commitOf = (context: Record<string, unknown>, trip: Record<string, unknown> = {}) =>
    baseRequest({
      message: '',
      trip,
      action: { name: 'search_flights', surfaceId: 'inline-1', context },
    });

  it('keeps what the traveler set', async () => {
    script.push({ chunks: ['Looking now.'] });
    const { result } = await collect(
      commitOf({ origin: 'JFK', startDate: '2027-04-12', endDate: '2027-04-19' }),
    );

    expect(result.trip).toMatchObject({
      origin: 'JFK',
      startDate: '2027-04-12',
      endDate: '2027-04-19',
    });
  });

  it('refuses a return before the departure, and keeps the rest', async () => {
    script.push({ chunks: ['That range will not work.'] });
    const { result } = await collect(
      commitOf(
        { origin: 'JFK', startDate: '2027-04-20', endDate: '2027-04-12' },
        { destination: 'Madrid' },
      ),
    );

    expect(result.trip['endDate']).toBeUndefined();
    // Everything that was fine still lands — a refusal is not a rollback.
    expect(result.trip).toMatchObject({
      destination: 'Madrid',
      origin: 'JFK',
      startDate: '2027-04-20',
    });
  });

  it('tells the model what it turned away', async () => {
    script.push({ chunks: ['Sorry — when are you back?'] });
    await collect(commitOf({ startDate: '2027-04-20', endDate: '2027-04-12' }));

    // Otherwise the model reads back the old trip and has no idea a value was
    // refused, so it never asks again.
    expect(sentText()).toContain('Refused');
    expect(sentText()).toContain('2027-04-12 is not after 2027-04-20');
  });

  it('refuses a party of nobody', async () => {
    script.push({ chunks: ['How many of you?'] });
    const { result } = await collect(commitOf({ travelers: 0 }, { travelers: 2 }));

    expect(result.trip['travelers']).toBe(2);
  });

  it('says nothing about a refusal when there was none', async () => {
    script.push({ chunks: ['On it.'] });
    await collect(commitOf({ origin: 'JFK' }));

    expect(sentText()).not.toContain('Refused');
  });
});

