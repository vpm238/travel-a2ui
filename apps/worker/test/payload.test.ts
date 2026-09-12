/**
 * What a turn actually sends.
 *
 * Not a correctness test — a scale, and a guard against the shape of cost
 * changing without anyone noticing. It drives ten turns through the real agent
 * loop against a scripted stream and adds up the request bodies.
 *
 * What it found is worth writing down, because it corrected an assumption.
 * Chaining turns with `previous_interaction_id` instead of re-uploading the
 * transcript saves about 2.5 kB across ten turns — real, and almost nothing.
 * The cost is the ~47 kB of system instruction and tool schemas that goes up on
 * *every* turn regardless. A conversation is not expensive because it is long;
 * it is expensive because each turn re-sends the contract.
 *
 * So the assertion here is that the per-turn payload stays **flat**. A turn that
 * grows with the conversation is the regression this is watching for; making the
 * flat part smaller is a separate problem, and a bigger one.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const bodies: string[] = [];
let index = 0;

function sse(id: number, text: string): string {
  return [
    { event_type: 'interaction.created', interaction: { id: `int_${id}` } },
    { event_type: 'step.delta', index: 0, delta: { type: 'text', text } },
    { event_type: 'step.stop', index: 0, step_usage: {} },
    { event_type: 'interaction.completed', interaction: { id: `int_${id}`, status: 'completed' } },
  ]
    .map((frame) => `data: ${JSON.stringify(frame)}\n\n`)
    .join('');
}

vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => {
  bodies.push(String(init.body ?? ''));
  return new Response(sse(index++, 'Here are three options.'), { status: 200 });
});

const { runTurn } = await import('../src/agent.js');

beforeEach(() => {
  bodies.length = 0;
  index = 0;
});

async function tenTurns(): Promise<number[]> {
  let interactionId: string | null = null;
  // Threaded exactly as the Worker threads it, because the panel redraw is
  // skipped only when the shape has not moved — a test that dropped it would
  // measure three requests a turn and call it the cost of a conversation.
  let shape: string | undefined;
  const trip: Record<string, unknown> = { destination: 'Madrid' };

  for (let turn = 0; turn < 10; turn += 1) {
    const result = await runTurn(
      {
        apiKey: 'k',
        model: 'gemini-3.8-flash',
        message: `Turn ${turn}: what about the next thing?`,
        interactionId,
        shape,
        trip,
        surface: 'inline' as const,
        surfaceId: `inline-${turn + 1}`,
        skill: 'express-monolithic' as const,
        effort: 'medium' as const,
      } as never,
      () => undefined,
    );
    interactionId = result.interactionId;
    shape = result.shape;
  }

  return bodies.map((body) => body.length);
}

/** Just the conversation turns — the panel redraws are not chained. */
const conversation = () =>
  bodies
    .map((body) => JSON.parse(body))
    .filter((body) => !String(body.input?.[0]?.content?.[0]?.text ?? '').startsWith('Redraw'));

describe('what a conversation costs to continue', () => {
  it('sends the same amount on the tenth turn as on the first', async () => {
    await tenTurns();
    const turns = conversation().map((body) => JSON.stringify(body).length);
    expect(turns).toHaveLength(10);
    // Only the turn's own message differs in length.
    expect(turns[9]! - turns[0]!).toBeLessThan(200);
  });

  /**
   * The panels are redrawn when the trip's decisions change shape, not every
   * turn. Ten turns over an unchanging trip cost two redraws — the first pair —
   * and nothing after that.
   */
  it('redraws the standing surfaces once, not per turn', async () => {
    await tenTurns();
    const redraws = bodies.length - conversation().length;
    expect(redraws).toBe(2);
  });

  it('chains rather than re-uploading the conversation', async () => {
    await tenTurns();
    const last = JSON.parse(bodies[9]!);
    expect(last.previous_interaction_id).toBe('int_8');
    // One message, not ten.
    expect(last.input).toHaveLength(1);
  });

  it('keeps the contract in the system instruction, where a prefix can be cached', async () => {
    await tenTurns();
    const first = JSON.parse(bodies[0]!);
    // The stable half leads, so every turn shares a prefix with the last.
    expect(first.system_instruction.indexOf('A2UI Express DSL Output Contract')).toBeLessThan(
      first.system_instruction.indexOf('inline-1'),
    );
  });
});
