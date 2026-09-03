/**
 * The agent loop, with a scripted model.
 *
 * The Anthropic client is replaced by a fake that replays a canned stream. That
 * makes the interesting things testable without spending a token or depending
 * on a model behaving the same way twice: does prose stay prose, does Express
 * become a surface *while it is still arriving*, do tool results go back in one
 * message, does a refusal end the turn cleanly.
 *
 * What is deliberately not mocked is the Express compiler — the whole risk in
 * this pipeline is between the model's text and the host's components, and a
 * mock there would test nothing.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

interface ScriptedTurn {
  /** Text chunks, delivered in order to the `text` handler. */
  chunks: string[];
  /** Content blocks on the final message; defaults to the joined text. */
  content?: any[];
  stopReason?: string;
  usage?: Partial<{
    input_tokens: number;
    output_tokens: number;
    cache_read_input_tokens: number;
    cache_creation_input_tokens: number;
  }>;
}

const script: ScriptedTurn[] = [];
const requests: any[] = [];
let failWith: Error | null = null;

class FakeAuthenticationError extends Error {}
class FakeAPIError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
  }
}

vi.mock('@anthropic-ai/sdk', () => {
  class FakeAnthropic {
    constructor(readonly options: { apiKey?: string }) {}

    messages = {
      stream: (request: any) => {
        requests.push(request);
        if (failWith) throw failWith;

        const turn = script.shift() ?? { chunks: [''] };
        const handlers: Record<string, Array<(value: string) => void>> = {};

        return {
          on(event: string, handler: (value: string) => void) {
            (handlers[event] ??= []).push(handler);
            return this;
          },
          async finalMessage() {
            // Deliver the stream first, exactly as the SDK does, so anything
            // reading `on('text')` sees it before the final message resolves.
            for (const chunk of turn.chunks) {
              for (const handler of handlers['text'] ?? []) handler(chunk);
            }
            return {
              content: turn.content ?? [{ type: 'text', text: turn.chunks.join('') }],
              stop_reason: turn.stopReason ?? 'end_turn',
              usage: {
                input_tokens: 100,
                output_tokens: 50,
                cache_read_input_tokens: 0,
                cache_creation_input_tokens: 0,
                ...turn.usage,
              },
            };
          },
        };
      },
    };

    static AuthenticationError = FakeAuthenticationError;
    static PermissionDeniedError = class extends Error {};
    static RateLimitError = class extends Error {};
    static BadRequestError = class extends Error {};
    static APIConnectionError = class extends Error {};
    static APIError = FakeAPIError;
  }

  return { default: FakeAnthropic, Anthropic: FakeAnthropic };
});

const { runTurn } = await import('../src/agent.js');
const { buildSystemPrompt, describeAllSkills, describeSkill } = await import('../src/skills.js');
const { trimHistory } = await import('../src/session.js');
const { runTool } = await import('../src/tools.js');
const { originForTimeZone } = await import('../src/travel.js');

function baseRequest(overrides: Record<string, unknown> = {}) {
  return {
    apiKey: 'sk-ant-test',
    model: 'claude-opus-5',
    message: 'Six days in Madrid',
    history: [],
    trip: {},
    surface: 'inline' as const,
    surfaceId: 'inline-1',
    skill: 'express-monolithic' as const,
    effort: 'medium' as const,
    ...overrides,
  };
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

    const done = events.filter((e) => e.type === 'ui' && e.done);
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
    const context = { trip, saveTrip: (patch: Record<string, unknown>) => Object.assign(trip, patch) };
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
      content: [
        { type: 'tool_use', id: 't1', name: 'search_flights', input: { destination: 'Madrid' } },
        { type: 'tool_use', id: 't2', name: 'get_weather', input: { destination: 'Madrid' } },
      ],
      stopReason: 'tool_use',
    });
    script.push({ chunks: ['Here you go.'] });

    const { events, result } = await collect();
    expect(events.filter((e) => e.type === 'tool')).toHaveLength(2);
    expect(events.filter((e) => e.type === 'tool_result')).toHaveLength(2);

    // Parallel calls must come back as one user message, or the model learns
    // to stop making them.
    const toolResults = result.history.filter(
      (message: any) =>
        message.role === 'user' &&
        Array.isArray(message.content) &&
        message.content[0]?.type === 'tool_result',
    );
    expect(toolResults).toHaveLength(1);
    expect((toolResults[0] as any).content).toHaveLength(2);
  });

  it('remembers what save_trip recorded', async () => {
    script.push({
      chunks: [''],
      content: [
        {
          type: 'tool_use',
          id: 't1',
          name: 'save_trip',
          input: { destination: 'Madrid', travelers: 2 },
        },
      ],
      stopReason: 'tool_use',
    });
    script.push({ chunks: ['Saved.'] });

    const { result } = await collect();
    expect(result.trip).toEqual({ destination: 'Madrid', travelers: 2 });
  });

  it('reports a failing tool without ending the turn', async () => {
    script.push({
      chunks: [''],
      content: [{ type: 'tool_use', id: 't1', name: 'not_a_tool', input: {} }],
      stopReason: 'tool_use',
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
        content: [{ type: 'tool_use', id: `t${index}`, name: 'get_trip', input: {} }],
        stopReason: 'tool_use',
      });
    }

    const { events } = await collect();
    const stopped = events.find((e) => e.type === 'error' && /rounds of tool calls/.test(e.message));
    expect(stopped).toBeTruthy();
  });
});

describe('the request the model receives', () => {
  it('carries the skill, with a cache breakpoint after the stable half', async () => {
    script.push({ chunks: ['ok'] });
    await collect();

    const [request] = requests;
    expect(request.system).toHaveLength(2);
    expect(request.system[0].cache_control).toEqual({ type: 'ephemeral' });
    expect(request.system[0].text).toContain('A2UI Express output contract');
    expect(request.system[1].cache_control).toBeUndefined();
    expect(request.system[1].text).toContain('inline-1');
  });

  it('sends the tools and the model and effort that were asked for', async () => {
    script.push({ chunks: ['ok'] });
    await collect(baseRequest({ model: 'claude-sonnet-5', effort: 'low' }));

    const [request] = requests;
    expect(request.model).toBe('claude-sonnet-5');
    expect(request.output_config.effort).toBe('low');
    expect(request.thinking).toEqual({ type: 'adaptive' });
    expect(request.tools.map((tool: any) => tool.name)).toContain('search_flights');
  });

  it('attaches on-screen values to the user turn', async () => {
    script.push({ chunks: ['ok'] });
    await collect(baseRequest({ surfaceState: { filters: { maxPrice: 600 } } }));
    expect(requests[0].messages[0].content).toContain('maxPrice');
  });
});

describe('failures', () => {
  it('explains a rejected key in words the user can act on', async () => {
    failWith = new FakeAuthenticationError('401');
    script.push({ chunks: [''] });

    const { events } = await collect();
    const error = events.find((e) => e.type === 'error');
    expect(error.message).toMatch(/rejected/i);
    expect(error.retryable).toBe(false);
  });

  it('ends the turn on a refusal', async () => {
    script.push({ chunks: [''], stopReason: 'refusal' });
    const { events, result } = await collect();
    expect(events.some((e) => e.type === 'error' && /declined/.test(e.message))).toBe(true);
    expect(result.stopReason).toBe('refusal');
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
      const correction = result.history.find(
        (message: any) =>
          message.role === 'user' && typeof message.content === 'string' &&
          message.content.includes('did not compile'),
      );
      expect(correction!.content).toContain("keyword arguments use '='");
      expect(correction!.content).toContain(BROKEN);

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
    const [stable] = buildSystemPrompt({
      variant: 'express-monolithic',
      surface: 'inline',
      surfaceId: 'inline-1',
      catalogId: 'https://example.test/catalog.json',
      trip: {},
      today: '2026-04-01',
    });
    expect(stable!.text.startsWith('---')).toBe(false);
    expect(stable!.text).not.toContain('protocol_version:');
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
      })[1]!.text;

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
      })[1]!.text;

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
    })[1]!.text;

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

describe('history trimming', () => {
  it('leaves a short conversation alone', () => {
    const history = Array.from({ length: 10 }, () => ({ role: 'user', content: 'hi' })) as any;
    expect(trimHistory(history)).toHaveLength(10);
  });

  it('never starts a trimmed history on a tool result', () => {
    const history: any[] = [];
    for (let index = 0; index < 30; index++) {
      history.push({ role: 'user', content: `turn ${index}` });
      history.push({ role: 'assistant', content: [{ type: 'tool_use', id: `t${index}` }] });
      history.push({ role: 'user', content: [{ type: 'tool_result', tool_use_id: `t${index}` }] });
    }

    const trimmed = trimHistory(history);
    expect(trimmed.length).toBeLessThan(history.length);
    const first = trimmed[0]!;
    expect(first.role).toBe('user');
    expect(typeof first.content === 'string' || !first.content.some((b: any) => b.type === 'tool_result')).toBe(
      true,
    );
  });
});
