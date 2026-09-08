/**
 * The agent loop.
 *
 * One turn is: send the conversation, stream the reply, run any tools it asked
 * for, send the results back, repeat until it stops asking. The interesting part
 * is what happens to the text on the way out.
 *
 * The model writes prose and A2UI Express in one stream. `ExpressStreamParser`
 * splits them as the tokens arrive and recompiles the open block on every chunk,
 * so the surface paints while the model is still typing rather than after it
 * stops. That is the whole reason for choosing Express over JSON: a partial
 * Express program is still a program.
 *
 * Everything this emits goes down one SSE channel to the browser, which is also
 * where tool activity and errors go, so the client has a single ordered story of
 * the turn.
 */

import Anthropic from '@anthropic-ai/sdk';
import {
  ExpressCompiler,
  ExpressStreamParser,
  bindCommitContext,
  type A2uiMessage,
} from '@travel-a2ui/express';

import catalog from '../../../catalogs/a2ui-travel/catalog.json';
import { buildSystemPrompt, type SkillVariant, type SurfaceKind } from './skills.js';
import { TOOLS, runTool, type ToolContext } from './tools.js';
import { originForTimeZone } from './travel.js';
import { normalize as normalizeTrip, type Trip } from '@travel-a2ui/trip';
import { STANDING_SURFACES, seedSurfaceTrip, tripUpdates } from './surface.js';

export const CATALOG = catalog as unknown as import('@travel-a2ui/express').CatalogSchema;
export const CATALOG_ID = String(CATALOG.catalogId);

/** Turn events, as the browser receives them. */
export type AgentEvent =
  | { type: 'start'; model: string; skill: SkillVariant; surfaceId: string }
  /**
   * Prose. `round` is the tool round it came from: the model says a sentence,
   * calls a tool, and says another, and those are separate paragraphs — glued
   * together they read as one sentence with a full stop in the middle.
   */
  | { type: 'text'; delta: string; round: number }
  | { type: 'ui'; surfaceId: string; messages: A2uiMessage[]; done: boolean }
  /**
   * A block the model wrote that would not compile.
   *
   * `source` says where it happened — mid-stream or on the finished message —
   * and `express` is the offending text, so a failure can be read rather than
   * guessed at.
   */
  | { type: 'ui_error'; message: string; source: string; express?: string }
  | { type: 'tool'; name: string; input: unknown; status: 'running' }
  | { type: 'tool_result'; name: string; result: unknown; isError: boolean }
  | { type: 'trip'; trip: Record<string, unknown> }
  | { type: 'usage'; inputTokens: number; outputTokens: number; cacheReadTokens: number; cacheWriteTokens: number }
  /** The model is being asked to rewrite a block that did not compile. */
  | { type: 'retry'; reason: string }
  | { type: 'error'; message: string; retryable: boolean }
  | { type: 'done'; stopReason: string | null };

/**
 * An interaction on a surface, in A2UI's own shape.
 *
 * This is what a renderer produces when someone presses something — any
 * renderer, on any platform, with nothing taught to it. It replaced a sentence
 * the browser used to compose (`[interface] search_flights (origin: "JFK")`),
 * which was a private protocol wearing the costume of a user message.
 *
 * `context` is the answer: the action's bound paths, resolved. `dataModel` is
 * the rest of the surface, opaque and optional — it keeps trip state exact
 * without asking any client to know what a trip is, and a client that omits it
 * still works.
 */
export interface SurfaceAction {
  name: string;
  surfaceId: string;
  sourceComponentId?: string;
  timestamp?: string;
  context: Record<string, unknown>;
  dataModel?: Record<string, unknown>;
}

export interface TurnRequest {
  apiKey: string;
  model: string;
  /** What the traveler typed. Empty when `action` carries the turn instead. */
  message: string;
  /** What the traveler pressed. */
  action?: SurfaceAction;
  history: Anthropic.MessageParam[];
  trip: Record<string, unknown>;
  /** The browser's timezone and locale, as a hint about the departure city. */
  client?: { timeZone?: string; locale?: string };
  surface: SurfaceKind;
  surfaceId: string;
  skill: SkillVariant;
  effort: 'low' | 'medium' | 'high';
}

export interface TurnResult {
  history: Anthropic.MessageParam[];
  trip: Record<string, unknown>;
  stopReason: string | null;
}

/** Tool loops need a ceiling: a model that keeps calling tools should stop, not bill. */
const MAX_TOOL_ROUNDS = 6;
const MAX_TOKENS = 16_000;

/** Text the model wrote outside `<a2ui>` blocks, per turn. */
function textOf(blocks: Anthropic.ContentBlock[]): string {
  return blocks
    .filter((block): block is Anthropic.TextBlock => block.type === 'text')
    .map((block) => block.text)
    .join('');
}

/**
 * The trip facts inside a committed surface's data model.
 *
 * Surfaces put shared facts under `/trip` by convention, so this is where a
 * date the traveler typed becomes a date the trip knows. `normalize` does the
 * filtering and the coercion: a surface's data model also holds whatever local
 * scratch the model invented for that card, and the values that *are* trip
 * fields arrive in whatever shape the control produced — a ChoicePicker's
 * `["economy"]`, a date input's RFC 3339 instant, a budget typed as "$2,600".
 */
function tripFromSurface(state: Record<string, unknown> | undefined): Trip {
  return normalizeTrip(state?.['trip']);
}

/**
 * The trip facts an action's own context carries.
 *
 * The context is the part of the surface the button *declared* it was sending,
 * so it is the authoritative half of an interaction — and on a client that
 * sends nothing else, the only half. Keys are matched against trip field names,
 * which is exactly what `bindCommitContext` produces when it fills in a path
 * the model left unbound.
 */
function tripFromContext(context: Record<string, unknown> | undefined): Trip {
  return normalizeTrip(context);
}

/**
 * What the model is told when someone presses something.
 *
 * The wire carries an action, not a sentence. The model still needs a sentence,
 * and this is the one place that decides what it says — which is where it
 * belongs: how this agent interprets a tap on a read-only panel is a fact about
 * this agent, not about the tap, and a client should not be in the business of
 * explaining it.
 */
function describeAction(action: SurfaceAction, surface: SurfaceKind): string {
  const said = JSON.stringify(action.context ?? {});
  const where = action.surfaceId;

  // A panel is a record, not a form. An interaction there is a request to
  // re-open a decision in the conversation, where there is one place to edit a
  // value and a history of when it changed.
  if (where === 'sidebar' || where === 'home') {
    const field = action.context?.['field'];
    if (field) {
      return (
        `[interface] The traveler pressed "${action.name}" on the ${where} for \`${String(field)}\`. ` +
        'Release that decision and ask for it again inline, pre-filled with what was there, ' +
        'along with anything that depended on it.'
      );
    }
    return (
      `[interface] The traveler pressed "${action.name}" on the ${where} (context ${said}). ` +
      'The panel is read-only — ask them that in the conversation instead, with the controls it needs.'
    );
  }

  return `[interface] ${action.name} on ${where} — context ${said}`;
}

export async function runTurn(
  request: TurnRequest,
  emit: (event: AgentEvent) => void,
): Promise<TurnResult> {
  const client = new Anthropic({
    apiKey: request.apiKey,
    // The browser holds the key and sends it per request; nothing is stored
    // here. One retry, because a Worker turn that hangs is worse than one that
    // fails and can be re-sent.
    maxRetries: 1,
  });

  const compiler = new ExpressCompiler(CATALOG, 'v0.9.1');
  // Values the traveler set on screen are facts, and the host records them
  // rather than depending on the model to notice and call `save_trip`. That
  // dependency is what made a second card forget what the first one asked.
  //
  // The action's own context first, then the rest of the surface: the context
  // is what the button declared it was sending, so it wins where they disagree,
  // and the surrounding data model fills in anything the traveler set that no
  // binding named.
  const trip = {
    ...request.trip,
    ...tripFromSurface(request.action?.dataModel),
    ...tripFromContext(request.action?.context),
  };
  const toolContext: ToolContext = {
    trip,
    saveTrip: (patch) => Object.assign(trip, patch),
  };

  const messages: Anthropic.MessageParam[] = [...request.history];

  // Pressing something *is* the traveler's turn, so it enters the conversation
  // as one. The sentence is written here rather than in the browser: the wire
  // carries the action, and what it means is the agent's to say.
  //
  // Typing wins when both arrive. Someone can type while a surface is on screen,
  // and then what they said is the turn — the action's values still reached the
  // trip above, which is the part that had to happen either way.
  const opening =
    request.message || (request.action ? describeAction(request.action, request.surface) : '');
  messages.push({ role: 'user', content: opening });

  emit({ type: 'start', model: request.model, skill: request.skill, surfaceId: request.surfaceId });

  const suggested = originForTimeZone(request.client?.timeZone);
  const system = buildSystemPrompt({
    variant: request.skill,
    surface: request.surface,
    surfaceId: request.surfaceId,
    catalogId: CATALOG_ID,
    trip,
    today: new Date().toISOString().slice(0, 10),
    ...(suggested && request.client?.timeZone
      ? {
          originHint: {
            code: suggested.code,
            city: suggested.city,
            timeZone: request.client.timeZone,
          },
        }
      : {}),
  });

  let stopReason: string | null = null;

  /**
   * A compile failure the model has not been told about yet.
   *
   * Until this existed, Express that did not compile ended the turn with a
   * broken surface and the model none the wiser — it had written something
   * wrong and nothing ever said so. The MCP tools have always answered a
   * compile error by naming it, because there the model is on the other side of
   * a tool call; here it is the same model, one message later.
   */
  let unreported: { message: string; express: string } | null = null;
  let retriedCompile = false;

  for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
    const stream = new ExpressStreamParser(compiler, {
      surfaceId: request.surfaceId,
      catalogId: CATALOG_ID,
      version: 'v0.9.1',
    });

    let assistantBlocks: Anthropic.ContentBlock[] = [];

    try {
      const run = client.messages.stream({
        model: request.model,
        max_tokens: MAX_TOKENS,
        system,
        messages,
        tools: TOOLS,
        thinking: { type: 'adaptive' },
        output_config: { effort: request.effort },
      });

      run.on('text', (delta) => {
        // Split prose from UI as it arrives, and recompile the open block.
        for (const event of stream.push(delta)) {
          if (event.type === 'text') emit({ type: 'text', delta: event.delta, round });
          else if (event.type === 'ui') {
            emit({
              type: 'ui',
              surfaceId: request.surfaceId,
              messages: bindCommitContext(seedSurfaceTrip(event.messages, trip)),
              done: event.done,
            });
          } else if (event.type === 'error') {
            unreported = { message: event.message, express: event.source };
            emit({
              type: 'ui_error',
              message: event.message,
              source: 'stream',
              express: event.source,
            });
          }
        }
      });

      const message = await run.finalMessage();
      assistantBlocks = message.content;
      stopReason = message.stop_reason;

      for (const event of stream.end()) {
        if (event.type === 'text') emit({ type: 'text', delta: event.delta, round });
        else if (event.type === 'ui') {
          emit({
            type: 'ui',
            surfaceId: request.surfaceId,
            messages: bindCommitContext(seedSurfaceTrip(event.messages, trip)),
            done: event.done,
          });
        } else if (event.type === 'error') {
          unreported = { message: event.message, express: event.source };
          emit({ type: 'ui_error', message: event.message, source: 'final', express: event.source });
        }
      }

      emit({
        type: 'usage',
        inputTokens: message.usage.input_tokens,
        outputTokens: message.usage.output_tokens,
        cacheReadTokens: message.usage.cache_read_input_tokens ?? 0,
        cacheWriteTokens: message.usage.cache_creation_input_tokens ?? 0,
      });

      if (message.stop_reason === 'refusal') {
        emit({
          type: 'error',
          message: 'The model declined this request.',
          retryable: false,
        });
        messages.push({ role: 'assistant', content: assistantBlocks });
        break;
      }
    } catch (error) {
      emit(describeApiError(error));
      break;
    }

    messages.push({ role: 'assistant', content: assistantBlocks });

    const toolUses = assistantBlocks.filter(
      (block): block is Anthropic.ToolUseBlock => block.type === 'tool_use',
    );

    // Nothing left to do but a surface that did not compile: hand the error
    // back and let it write the block again. Once — a model that cannot fix it
    // on the second attempt will not fix it on the fifth, and the traveler is
    // waiting.
    if (toolUses.length === 0 && unreported && !retriedCompile) {
      retriedCompile = true;
      const failure = unreported;
      unreported = null;
      emit({ type: 'retry', reason: failure.message });
      messages.push({
        role: 'user',
        content:
          'That A2UI block did not compile, so nothing was drawn and the traveler is looking ' +
          `at prose with a gap in it.\n\n${failure.message}\n\nThe block was:\n\n` +
          `${failure.express.slice(0, 4000)}\n\n` +
          'Write the whole block again, corrected. Do not repeat the prose — only the ' +
          '<a2ui> block.',
      });
      continue;
    }

    if (toolUses.length === 0) break;

    // Parallel tool calls come back in one assistant message and their results
    // must go back in one user message — splitting them teaches the model to
    // stop calling tools in parallel.
    const results: Anthropic.ToolResultBlockParam[] = [];
    for (const use of toolUses) {
      emit({ type: 'tool', name: use.name, input: use.input, status: 'running' });
      const { result, isError } = await runTool(
        use.name,
        (use.input ?? {}) as Record<string, unknown>,
        toolContext,
      );
      emit({ type: 'tool_result', name: use.name, result, isError });
      results.push({
        type: 'tool_result',
        tool_use_id: use.id,
        content: JSON.stringify(result),
        is_error: isError,
      });
    }

    messages.push({ role: 'user', content: results });
    emit({ type: 'trip', trip: { ...trip } });

    if (round === MAX_TOOL_ROUNDS - 1) {
      emit({
        type: 'error',
        message: `Stopped after ${MAX_TOOL_ROUNDS} rounds of tool calls.`,
        retryable: true,
      });
    }
  }

  emit({ type: 'trip', trip: { ...trip } });
  // The panels outlive the turn that drew them, so the trip reaches them as
  // ordinary A2UI rather than as something the client works out for itself.
  for (const surfaceId of STANDING_SURFACES) {
    const updates = tripUpdates(surfaceId, trip);
    if (updates.length > 0) emit({ type: 'ui', surfaceId, messages: updates, done: true });
  }
  emit({ type: 'done', stopReason });

  return { history: messages, trip, stopReason };
}

/**
 * Turns an SDK error into something the user can act on.
 *
 * "401" is not a message; "that key was rejected" is. Because the key comes from
 * the person sitting in front of the app, auth failures are the most likely
 * error here and deserve the clearest wording.
 */
export function describeApiError(error: unknown): AgentEvent & { type: 'error' } {
  if (error instanceof Anthropic.AuthenticationError) {
    return {
      type: 'error',
      message: 'That API key was rejected. Check it starts with sk-ant- and is still active.',
      retryable: false,
    };
  }
  if (error instanceof Anthropic.PermissionDeniedError) {
    return {
      type: 'error',
      message: 'That key does not have access to this model. Try a different model or key.',
      retryable: false,
    };
  }
  if (error instanceof Anthropic.RateLimitError) {
    return { type: 'error', message: 'Rate limited by the API. Wait a moment and retry.', retryable: true };
  }
  if (error instanceof Anthropic.BadRequestError) {
    return { type: 'error', message: `The API rejected the request: ${error.message}`, retryable: false };
  }
  if (error instanceof Anthropic.APIConnectionError) {
    return { type: 'error', message: 'Could not reach the API. Check the connection and retry.', retryable: true };
  }
  if (error instanceof Anthropic.APIError) {
    return { type: 'error', message: `API error ${error.status}: ${error.message}`, retryable: (error.status ?? 0) >= 500 };
  }
  return {
    type: 'error',
    message: error instanceof Error ? error.message : String(error),
    retryable: false,
  };
}

/** Used by the MCP server, which has no stream to write into. */
export async function runTurnCollected(request: TurnRequest): Promise<{
  text: string;
  ui: A2uiMessage[];
  trip: Record<string, unknown>;
  error?: string;
}> {
  const chunks: string[] = [];
  let ui: A2uiMessage[] = [];
  let error: string | undefined;

  const result = await runTurn(request, (event) => {
    if (event.type === 'text') chunks.push(event.delta);
    else if (event.type === 'ui' && event.done) ui = event.messages;
    else if (event.type === 'error') error = event.message;
  });

  return { text: chunks.join('').trim(), ui, trip: result.trip, ...(error ? { error } : {}) };
}

export { textOf };
