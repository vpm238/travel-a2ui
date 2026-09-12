/**
 * Reading the Interactions stream.
 *
 * Every case here is a frame shape taken off the wire from a real turn, because
 * both bugs this file exists for were invisible to a scripted test that agreed
 * with the parser. The app passed 284 tests while calling every one of its
 * tools with no arguments at all.
 */

import { describe, expect, it, vi } from 'vitest';

import { streamInteraction } from '../src/gemini.js';

type Frame = Record<string, unknown>;

/** Serves one scripted stream and records the request body it was asked with. */
function serve(frames: Frame[]): { sent: () => Record<string, unknown> } {
  let body: Record<string, unknown> = {};
  vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => {
    body = JSON.parse(String(init.body ?? '{}'));
    return new Response(frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join(''), {
      status: 200,
    });
  });
  return { sent: () => body };
}

const run = (frames: Frame[], extra: Record<string, unknown> = {}) => {
  serve(frames);
  return streamInteraction(
    { apiKey: 'k', model: 'gemini-3.8-flash', input: [], ...extra },
    () => {},
  );
};

describe('tool arguments', () => {
  /**
   * The frame that broke it. A streamed call opens with `arguments: {}` — an
   * empty object, which is truthy — and the real arguments follow as deltas.
   * Seeding the buffer with that `{}` produced `{}{"destination":"Madrid"}`,
   * which parses as nothing, so `save_trip` saved nothing and the agent asked
   * for a destination the traveler had already given it.
   */
  it('ignores the empty placeholder a streamed call opens with', async () => {
    const result = await run([
      {
        event_type: 'step.start',
        index: 0,
        step: { id: 'call_1', type: 'function_call', name: 'save_trip', arguments: {} },
      },
      {
        event_type: 'step.delta',
        index: 0,
        delta: { type: 'arguments_delta', arguments: '{"destination":"Madrid"}' },
      },
      { event_type: 'step.stop', index: 0 },
    ]);

    expect(result.toolCalls).toEqual([
      { id: 'call_1', name: 'save_trip', args: { destination: 'Madrid' } },
    ]);
  });

  it('keeps a call whose arguments arrived whole', async () => {
    const result = await run([
      {
        event_type: 'step.start',
        index: 0,
        step: { id: 'c', type: 'function_call', name: 'get_trip', arguments: { scope: 'all' } },
      },
      { event_type: 'step.stop', index: 0 },
    ]);

    expect(result.toolCalls[0]?.args).toEqual({ scope: 'all' });
  });

  it('reassembles arguments split across deltas', async () => {
    const result = await run([
      {
        event_type: 'step.start',
        index: 0,
        step: { id: 'c', type: 'function_call', name: 'save_trip', arguments: {} },
      },
      { event_type: 'step.delta', index: 0, delta: { type: 'arguments_delta', arguments: '{"ori' } },
      {
        event_type: 'step.delta',
        index: 0,
        delta: { type: 'arguments_delta', arguments: 'gin":"JFK"}' },
      },
      { event_type: 'step.stop', index: 0 },
    ]);

    expect(result.toolCalls[0]?.args).toEqual({ origin: 'JFK' });
  });
});

describe('usage', () => {
  /**
   * A plain model turn reports usage once, on `interaction.completed`, and
   * reports the interaction's total. Reading it off `step.stop` — which is
   * where a *managed agent* reports it — showed every model turn costing
   * nothing, which is exactly as useful as not reporting it.
   */
  it('reads the total a model turn reports when it completes', async () => {
    const result = await run([
      { event_type: 'step.stop', index: 0 },
      {
        event_type: 'interaction.completed',
        interaction: {
          id: 'int_1',
          status: 'completed',
          usage: {
            total_input_tokens: 12605,
            total_output_tokens: 335,
            total_cached_tokens: 128,
            total_thought_tokens: 3543,
          },
        },
      },
    ]);

    expect(result.usage).toEqual({
      inputTokens: 12605,
      outputTokens: 335,
      cachedTokens: 128,
      thoughtTokens: 3543,
    });
  });

  /** A managed agent reports per step, and `step_usage` is the step's share. */
  it('adds up the per-step usage an agent turn reports', async () => {
    const result = await run([
      {
        event_type: 'step.stop',
        index: 0,
        step_usage: { total_input_tokens: 7322, total_output_tokens: 87 },
        usage: { total_input_tokens: 7322, total_output_tokens: 87 },
      },
      {
        event_type: 'step.stop',
        index: 1,
        step_usage: { total_input_tokens: 3978, total_output_tokens: 32 },
        // The running total, which is why adding both fields double-counts.
        usage: { total_input_tokens: 11300, total_output_tokens: 119 },
      },
    ]);

    expect(result.usage.inputTokens).toBe(11300);
    expect(result.usage.outputTokens).toBe(119);
  });
});

describe('the request', () => {
  it('sends a thinking level only when one was asked for', async () => {
    const withLevel = serve([]);
    await streamInteraction(
      { apiKey: 'k', model: 'gemini-3.8-flash', input: [], thinkingLevel: 'low' },
      () => {},
    );
    expect(withLevel.sent()['generation_config']).toEqual({ thinking_level: 'low' });

    const without = serve([]);
    await streamInteraction({ apiKey: 'k', model: 'gemini-3.8-flash', input: [] }, () => {});
    expect(without.sent()).not.toHaveProperty('generation_config');
  });

  it('names an agent instead of a model when given one', async () => {
    const server = serve([]);
    await streamInteraction({ apiKey: 'k', agent: 'travel-a2ui', input: [] }, () => {});
    expect(server.sent()['agent']).toBe('travel-a2ui');
    expect(server.sent()).not.toHaveProperty('model');
  });
});
