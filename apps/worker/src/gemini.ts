/**
 * The Gemini Interactions API, as much of it as this agent needs.
 *
 * One endpoint does both jobs here: a plain model turn and a managed
 * (Antigravity) agent turn differ only by which `model` or `agent` you name, so
 * the Worker and the managed backend speak the same protocol and the runtime
 * picker stays a one-field change rather than two client libraries.
 *
 * Two things about it are worth knowing before reading the code.
 *
 * **The server keeps the conversation.** `previous_interaction_id` chains a turn
 * to the one before it, so the history does not go back up the wire every round.
 * That is the single biggest latency win available here — a ten-turn trip was
 * re-sending ten turns of prose and tool results to ask one more question.
 *
 * **Everything is a step.** Text, tool calls and their results all arrive as
 * `step.delta` events discriminated by `delta.type`, with `step.start` opening a
 * step and `step.stop` closing it with usage. Tool arguments stream as partial
 * JSON that only parses once the step stops, which is why they are buffered per
 * step index rather than parsed on arrival.
 *
 * It is a preview API, so parsing is deliberately forgiving: an event shape that
 * changes underneath us should cost a feature, not the turn.
 */

const ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/interactions';

/** What the traveler or the tools are handing to the model this round. */
export type InteractionInput =
  | { type: 'user_input'; content: Array<{ type: 'text'; text: string }> }
  | {
      type: 'function_result';
      name: string;
      call_id: string;
      result: Array<{ type: 'text'; text: string }>;
    };

export interface FunctionTool {
  type: 'function';
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

/** A tool call, once its streamed arguments have finished arriving. */
export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

export interface Usage {
  inputTokens: number;
  outputTokens: number;
  /** Reported when the API says part of the input was served from cache. */
  cachedTokens: number;
  /**
   * Thinking. Billed as output and, on a Flash turn that only has to compose a
   * surface, routinely larger than the surface itself — so it is reported
   * separately rather than folded into `outputTokens`, where nobody would see
   * that it is where the turn actually went.
   */
  thoughtTokens: number;
}

export interface InteractionResult {
  /** Chain the next turn to this to keep the conversation server-side. */
  interactionId: string | null;
  toolCalls: ToolCall[];
  text: string;
  usage: Usage;
  status: string | null;
}

export interface InteractionRequest {
  apiKey: string;
  /** A model id, or an agent id for a managed (Antigravity) agent. */
  model?: string;
  agent?: string;
  input: InteractionInput[];
  tools?: FunctionTool[];
  systemInstruction?: string;
  /**
   * How hard to think. Measured on Flash 3.8: `low` spends no thought tokens at
   * all and answers in about half the time of `medium`. Composing a surface
   * from a catalog the prompt already pins down is not a reasoning problem, and
   * a turn that thought for 3,500 tokens to emit 335 is spending the traveler's
   * time on nothing they will ever see.
   */
  thinkingLevel?: 'low' | 'medium' | 'high';
  previousInteractionId?: string | null;
  signal?: AbortSignal;
}

/** An open step, accumulating until `step.stop` says it is whole. */
interface PendingStep {
  id: string;
  name: string;
  args: string;
}

export class GeminiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly retryable: boolean,
  ) {
    super(message);
    this.name = 'GeminiError';
  }
}

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

/** One usage block, wherever it was reported. */
const readUsage = (usage: Record<string, unknown>): Usage => ({
  inputTokens: Number(usage['total_input_tokens'] ?? 0),
  outputTokens: Number(usage['total_output_tokens'] ?? 0),
  cachedTokens: Number(usage['total_cached_tokens'] ?? 0),
  thoughtTokens: Number(usage['total_thought_tokens'] ?? 0),
});

/**
 * Runs one interaction, streaming text out as it arrives.
 *
 * Returns once the interaction completes, with whatever tool calls it asked
 * for. The caller runs them and calls again with `function_result` inputs and
 * this interaction's id — that loop is the agent.
 */
export async function streamInteraction(
  request: InteractionRequest,
  onText: (delta: string) => void,
): Promise<InteractionResult> {
  const body: Record<string, unknown> = {
    input: request.input,
    stream: true,
    ...(request.agent ? { agent: request.agent } : { model: request.model }),
    ...(request.systemInstruction ? { system_instruction: request.systemInstruction } : {}),
    ...(request.tools?.length ? { tools: request.tools } : {}),
    ...(request.thinkingLevel
      ? { generation_config: { thinking_level: request.thinkingLevel } }
      : {}),
    ...(request.previousInteractionId
      ? { previous_interaction_id: request.previousInteractionId }
      : {}),
  };

  const response = await fetch(`${ENDPOINT}?alt=sse`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-goog-api-key': request.apiKey,
    },
    body: JSON.stringify(body),
    ...(request.signal ? { signal: request.signal } : {}),
  });

  if (!response.ok || !response.body) {
    const detail = await response.text().catch(() => '');
    throw toError(response.status, detail);
  }

  const result: InteractionResult = {
    interactionId: null,
    toolCalls: [],
    text: '',
    usage: { inputTokens: 0, outputTokens: 0, cachedTokens: 0, thoughtTokens: 0 },
    status: null,
  };

  // Steps are addressed by index, and a tool call's arguments arrive across
  // several deltas as partial JSON — whole only once the step stops.
  const open = new Map<number, PendingStep>();

  for await (const event of sseEvents(response.body, request.signal)) {
    const kind = String(event['event_type'] ?? '');
    const index = typeof event['index'] === 'number' ? event['index'] : 0;

    switch (kind) {
      case 'interaction.created':
      case 'interaction.completed': {
        const interaction = asRecord(event['interaction']);
        if (typeof interaction['id'] === 'string') result.interactionId = interaction['id'];
        if (typeof interaction['status'] === 'string') result.status = interaction['status'];
        // A plain model turn reports usage *only* here, and reports the whole
        // interaction's total — so this replaces the per-step tally rather than
        // adding to it. Reading it off `step.stop` alone, which is what this
        // did first, showed every model turn costing nothing.
        if (interaction['usage']) result.usage = readUsage(asRecord(interaction['usage']));
        break;
      }

      case 'step.start': {
        const step = asRecord(event['step']);
        if (step['type'] === 'function_call') {
          // Some calls arrive whole rather than streamed — but the streamed
          // ones open with `arguments: {}`, which is truthy. Seeding the buffer
          // with that `{}` and then appending the real deltas produced
          // `{}{"destination":"Madrid"}`, which parses as nothing: every tool
          // in the app was being called with no arguments at all. Only a
          // non-empty object is a whole call.
          const whole = asRecord(step['arguments']);
          open.set(index, {
            id: String(step['id'] ?? `call_${index}`),
            name: String(step['name'] ?? ''),
            args: Object.keys(whole).length > 0 ? JSON.stringify(whole) : '',
          });
        }
        break;
      }

      case 'step.delta': {
        const delta = asRecord(event['delta']);
        const type = String(delta['type'] ?? '');
        if (type === 'text' && typeof delta['text'] === 'string') {
          result.text += delta['text'];
          onText(delta['text']);
        } else if (type === 'arguments_delta' || type === 'arguments') {
          const chunk = delta['arguments'] ?? delta['partial_arguments'];
          if (typeof chunk === 'string') {
            const step = open.get(index) ?? { id: `call_${index}`, name: '', args: '' };
            step.args += chunk;
            open.set(index, step);
          }
        }
        break;
      }

      case 'step.stop': {
        // `step_usage` is this step; the sibling `usage` is the running total,
        // so adding both would double-count. A managed agent reports here and
        // a plain model does not, which is why this is a tally and
        // `interaction.completed` is allowed to replace it.
        if (event['step_usage']) {
          const step = readUsage(asRecord(event['step_usage']));
          result.usage.inputTokens += step.inputTokens;
          result.usage.outputTokens += step.outputTokens;
          result.usage.cachedTokens += step.cachedTokens;
          result.usage.thoughtTokens += step.thoughtTokens;
        }

        const step = open.get(index);
        if (step?.name) {
          open.delete(index);
          result.toolCalls.push({ id: step.id, name: step.name, args: parseArgs(step.args) });
        }
        break;
      }

      case 'error': {
        const error = asRecord(event['error']);
        throw new GeminiError(
          String(error['message'] ?? 'The model reported an error mid-stream.'),
          Number(error['code'] ?? 500),
          true,
        );
      }

      default:
        break;
    }
  }

  // A stream that ends without `step.stop` still owes us its calls; dropping
  // them would end the turn silently having done nothing.
  for (const step of open.values()) {
    if (step.name) result.toolCalls.push({ id: step.id, name: step.name, args: parseArgs(step.args) });
  }

  return result;
}

/** Streamed tool arguments, which are only valid JSON once they are complete. */
function parseArgs(raw: string): Record<string, unknown> {
  if (!raw.trim()) return {};
  try {
    return asRecord(JSON.parse(raw));
  } catch {
    // A truncated argument list is better handled by the tool's own "what are
    // you missing" path than by ending the turn.
    return {};
  }
}

/** `data:` lines off an SSE body, parsed, one event at a time. */
async function* sseEvents(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<Record<string, unknown>> {
  const reader = body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';

  try {
    for (;;) {
      if (signal?.aborted) return;
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;

      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const payload = frame
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trim())
          .join('');
        if (payload && payload !== '[DONE]') {
          try {
            yield asRecord(JSON.parse(payload));
          } catch {
            /* a frame we cannot parse is not a reason to drop the stream */
          }
        }
        boundary = buffer.indexOf('\n\n');
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
  }
}

/** An HTTP failure turned into something the traveler can act on. */
function toError(status: number, detail: string): GeminiError {
  let message = detail.slice(0, 300);
  try {
    const parsed = asRecord(JSON.parse(detail));
    const error = asRecord(parsed['error']);
    if (typeof error['message'] === 'string') message = error['message'];
  } catch {
    /* not JSON; the raw body is the best we have */
  }

  if (status === 401 || status === 403) {
    return new GeminiError(
      'That Gemini API key was rejected. Check it at aistudio.google.com/apikey.',
      status,
      false,
    );
  }
  if (status === 429) {
    return new GeminiError('Rate limited by the Gemini API. Try again in a moment.', status, true);
  }
  if (status >= 500) {
    return new GeminiError(`The Gemini API is having trouble (${status}).`, status, true);
  }
  return new GeminiError(message || `Gemini API error ${status}`, status, false);
}
