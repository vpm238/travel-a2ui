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

import {
  ExpressCompiler,
  ExpressStreamParser,
  bindCommitContext,
  bindDerivedLabels,
  stripPanelActions,
  type A2uiMessage,
} from '@travel-a2ui/express';

import catalog from '../../../catalogs/a2ui-travel/catalog.json';
import { buildSystemPrompt, type SkillVariant, type SurfaceKind } from './skills.js';
import { geminiTools, runTool, type ToolContext } from './tools.js';
import { GeminiError, streamInteraction, type InteractionInput } from './gemini.js';
import { originForTimeZone } from './travel.js';
import {
  confirm,
  decisionShape,
  merge as mergeTrip,
  normalize as normalizeTrip,
  problems,
  type Trip,
  type TripKey,
} from '@travel-a2ui/trip';
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
  | {
      type: 'usage';
      inputTokens: number;
      outputTokens: number;
      cacheReadTokens: number;
      cacheWriteTokens: number;
      thoughtTokens: number;
    }
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
  /**
   * The last interaction in this conversation, or null to start a new one.
   *
   * The transcript lives on the server; this is the thread back to it. A turn
   * therefore sends one message rather than the whole conversation, which is
   * where most of the old latency went.
   */
  interactionId?: string | null;
  trip: Record<string, unknown>;
  /** The browser's timezone and locale, as a hint about the departure city. */
  client?: { timeZone?: string; locale?: string };
  surface: SurfaceKind;
  surfaceId: string;
  skill: SkillVariant;
  effort: 'low' | 'medium' | 'high';
  /** The decision shape the standing surfaces were last drawn for. */
  shape?: string | null;
  /** Aborts the upstream request when the traveler presses Stop. */
  signal?: AbortSignal;
}

export interface TurnResult {
  /** Pass to the next turn to continue this conversation. */
  interactionId: string | null;
  trip: Record<string, unknown>;
  stopReason: string | null;
  /**
   * The trip's decision shape as the panels were last drawn for it. Saved with
   * the session so the next turn knows whether a redraw is owed.
   */
  shape?: string;
}

/** Tool loops need a ceiling: a model that keeps calling tools should stop, not bill. */
const MAX_TOOL_ROUNDS = 6;

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

/** Today, in the one format every date in this app is written in. */
const today = (): string => new Date().toISOString().slice(0, 10);

/** Values a commit is not allowed to corrupt the trip with. */
const REFUSABLE = new Set<TripKey>(['startDate', 'endDate', 'travelers', 'legs']);

/**
 * Applies what a surface sent, minus anything that would break the trip.
 *
 * `save_trip` has always validated, so a model that invented a return date
 * before the departure was told so. A *commit* went nowhere near it: the
 * traveler's own values were merged straight in, and a picker that handed back
 * 20 April → 12 April priced four flights against a trip with negative nights.
 * The doc has said "return before departure — refused at save" since before any
 * of this was written; it was only ever true of one of the two ways a value
 * arrives.
 *
 * A refused field reverts to what was saved, and the model is told which and
 * why, so the next surface re-asks instead of the traveler wondering why their
 * dates did not stick.
 */
function commit(saved: Trip, proposed: Trip): { trip: Trip; refused: string[] } {
  const found = problems(proposed, today()).filter((problem) => REFUSABLE.has(problem.field));
  if (found.length === 0) return { trip: proposed, refused: [] };

  const trip = { ...proposed };
  for (const problem of found) {
    // Back to what was saved — deleting outright would lose a value the
    // traveler had already agreed to, which is a second wrong answer.
    if (problem.field in saved) {
      (trip as Record<string, unknown>)[problem.field] = saved[problem.field];
    } else {
      delete (trip as Record<string, unknown>)[problem.field];
    }
  }
  return { trip, refused: found.map((problem) => problem.message) };
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
  const compiler = new ExpressCompiler(CATALOG, 'v0.9.1');

  // Values the traveler set on screen are facts, and the host records them
  // rather than depending on the model to notice and call `save_trip`. That
  // dependency is what made a second card forget what the first one asked.
  //
  // The action's own context first, then the rest of the surface: the context
  // is what the button declared it was sending, so it wins where they disagree,
  // and the surrounding data model fills in anything the traveler set that no
  // binding named.
  const fromSurface = tripFromSurface(request.action?.dataModel);
  const fromContext = tripFromContext(request.action?.context);
  const { trip, refused } = commit(request.trip, {
    ...request.trip,
    ...fromSurface,
    ...fromContext,
  });

  // Pressing a button *is* saying so. Whatever the surface sent stops being a
  // guess, however it got into the control — the agent's suggestion, a value
  // carried over from an earlier turn, or something typed just now.
  const said = [...Object.keys(fromSurface), ...Object.keys(fromContext)];
  if (said.length > 0) Object.assign(trip, confirm(trip, said));
  const toolContext: ToolContext = {
    trip,
    // `merge` rather than `Object.assign`, because one field does not simply
    // overwrite: a patch naming `assumed` is talking about its own fields, and
    // a later patch that states one of them for real has to clear that mark.
    saveTrip: (patch) => {
      const next = mergeTrip(trip, patch);
      for (const key of Object.keys(trip)) delete (trip as Record<string, unknown>)[key];
      Object.assign(trip, next);
    },
  };

  // Pressing something *is* the traveler's turn, so it enters the conversation
  // as one. The sentence is written here rather than in the browser: the wire
  // carries the action, and what it means is the agent's to say.
  //
  // Typing wins when both arrive. Someone can type while a surface is on screen,
  // and then what they said is the turn — the action's values still reached the
  // trip above, which is the part that had to happen either way.
  const opening = [
    request.message ||
      (request.action
        ? describeAction(request.action, request.surface)
        : // Nothing said, on a standing surface: the client asked for the panel
          // and the brief is the agent's to write.
          PANEL_REQUEST),
    // Said in the turn rather than left for the model to discover, because it
    // will not: the trip it reads back is simply the old one, and nothing in it
    // says a value was turned away.
    ...(refused.length
      ? [
          `[interface] Refused, and not saved: ${refused.join(' ')} ` +
            'Say so plainly and ask for it again, keeping everything else they set.',
        ]
      : []),
  ]
    .filter(Boolean)
    .join('\n\n');

  let input: InteractionInput[] = [
    { type: 'user_input', content: [{ type: 'text', text: opening }] },
  ];
  // The conversation lives on the server. This is the thread we are pulling.
  let previousInteractionId = request.interactionId ?? null;

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
  // A holder rather than a plain `let`: it is written inside the stream
  // callback, and control-flow analysis cannot see across that call, so a bare
  // variable reads as never-assigned at the point it is checked.
  const unreported: { failure: { message: string; express: string } | null } = { failure: null };
  let retriedCompile = false;

  for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
    // A fresh splitter per round: each round is its own stream of prose and
    // Express, and a block left open at the end of one is not continued by the
    // next.
    const stream = new ExpressStreamParser(compiler, {
      surfaceId: request.surfaceId,
      catalogId: CATALOG_ID,
      version: 'v0.9.1',
    });

    const drain = (events: ReturnType<ExpressStreamParser['push']>, source: string): void => {
      for (const event of events) {
        if (event.type === 'text') {
          emit({ type: 'text', delta: event.delta, round });
        } else if (event.type === 'ui') {
          emit({
            type: 'ui',
            surfaceId: request.surfaceId,
            messages: stripPanelActions(
              bindDerivedLabels(bindCommitContext(seedSurfaceTrip(event.messages, trip))),
              STANDING_SURFACES,
            ),
            done: event.done,
          });
        } else if (event.type === 'error') {
          unreported.failure = { message: event.message, express: event.source };
          emit({ type: 'ui_error', message: event.message, source, express: event.source });
        }
      }
    };

    let result;
    try {
      result = await streamInteraction(
        {
          apiKey: request.apiKey,
          model: request.model,
          input,
          tools: geminiTools(),
          systemInstruction: system,
          thinkingLevel: request.effort,
          previousInteractionId,
          ...(request.signal ? { signal: request.signal } : {}),
        },
        // Split prose from UI as it arrives, so the surface paints while the
        // model is still typing rather than after it stops.
        (delta) => drain(stream.push(delta), 'stream'),
      );
      drain(stream.end(), 'final');
    } catch (error) {
      emit(describeApiError(error));
      break;
    }

    previousInteractionId = result.interactionId ?? previousInteractionId;
    stopReason = result.status;

    emit({
      type: 'usage',
      inputTokens: result.usage.inputTokens,
      outputTokens: result.usage.outputTokens,
      cacheReadTokens: result.usage.cachedTokens,
      cacheWriteTokens: 0,
      thoughtTokens: result.usage.thoughtTokens,
    });

    // Nothing left to do but a surface that did not compile: hand the error
    // back and let it write the block again. Once — a model that cannot fix it
    // on the second attempt will not fix it on the fifth, and the traveler is
    // waiting.
    if (result.toolCalls.length === 0 && unreported.failure && !retriedCompile) {
      retriedCompile = true;
      const failure = unreported.failure;
      unreported.failure = null;
      emit({ type: 'retry', reason: failure.message });
      input = [
        {
          type: 'user_input',
          content: [
            {
              type: 'text',
              text:
                'That A2UI block did not compile, so nothing was drawn and the traveler is ' +
                `looking at prose with a gap in it.\n\n${failure.message}\n\nThe block was:` +
                `\n\n${failure.express.slice(0, 4000)}\n\n` +
                'Write the whole block again, corrected. Do not repeat the prose — only the ' +
                '<a2ui> block.',
            },
          ],
        },
      ];
      continue;
    }

    if (result.toolCalls.length === 0) break;

    // Every call this round answered in one go: the next request carries all of
    // their results, which is what keeps the model calling tools in parallel
    // rather than learning to ask one at a time.
    const results: InteractionInput[] = [];
    for (const call of result.toolCalls) {
      emit({ type: 'tool', name: call.name, input: call.args, status: 'running' });
      const { result: output, isError } = await runTool(call.name, call.args, toolContext);
      emit({ type: 'tool_result', name: call.name, result: output, isError });
      results.push({
        type: 'function_result',
        name: call.name,
        call_id: call.id,
        result: [{ type: 'text', text: JSON.stringify(output) }],
      });
    }

    input = results;
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

  // A rebuild, when the decisions changed shape enough to need different
  // controls. This is the last thing the browser was still deciding for itself:
  // it held a list of trip field names, watched them, and sent a prose prompt
  // asking for a new panel. Two problems with that, and the second is the
  // serious one — a prose prompt composed in a client is the private protocol
  // recommendation 4 removed from form submission, and a Swift client that does
  // not send it simply never gets a panel at all.
  const rebuilt =
    request.surface === 'inline' ? await rebuildPanels(request, trip, system, emit) : null;

  emit({ type: 'done', stopReason });

  return {
    interactionId: previousInteractionId,
    trip,
    stopReason,
    ...(rebuilt ? { shape: rebuilt } : {}),
  };
}

/**
 * Redraws the standing surfaces, if the trip's decisions changed shape.
 *
 * One extra model turn, and only when the shape moved — which is the same
 * budget the browser was spending, now spent by the thing that knows when it is
 * warranted. `decisionShape` lives in `packages/trip` because what counts as a
 * decision is a fact about a trip, not about a panel.
 *
 * A failure here is silent on purpose: the traveler's answer already arrived
 * and painted. A panel that is one turn stale is a much smaller problem than an
 * error banner over a conversation that went fine.
 */
async function rebuildPanels(
  request: TurnRequest,
  trip: Record<string, unknown>,
  _system: string,
  emit: (event: AgentEvent) => void,
): Promise<string | null> {
  const shape = decisionShape(trip as Trip);
  if (shape === request.shape) return shape;
  // Nothing to draw a panel *of* yet. The first turn of a conversation usually
  // ends with a question, and a panel saying "no trip" is a panel nobody wants.
  if (!trip['destination']) return shape;

  for (const surfaceId of STANDING_SURFACES) {
    const surface = surfaceId as SurfaceKind;
    const system = buildSystemPrompt({
      variant: request.skill,
      surface,
      surfaceId,
      catalogId: CATALOG_ID,
      trip,
      today: today(),
    });

    const stream = new ExpressStreamParser(new ExpressCompiler(CATALOG, 'v0.9.1'), {
      surfaceId,
      catalogId: CATALOG_ID,
      version: 'v0.9.1',
    });
    const drain = (events: ReturnType<ExpressStreamParser['push']>): void => {
      for (const event of events) {
        if (event.type !== 'ui') continue;
        emit({
          type: 'ui',
          surfaceId,
          messages: stripPanelActions(
            bindDerivedLabels(bindCommitContext(seedSurfaceTrip(event.messages, trip))),
            STANDING_SURFACES,
          ),
          done: event.done,
        });
      }
    };

    try {
      await streamInteraction(
        {
          apiKey: request.apiKey,
          model: request.model,
          // Not chained to the conversation: a panel redraw is not something the
          // traveler said, and threading it through `previous_interaction_id`
          // would put "rebuild the panel" in the transcript as a user turn.
          input: [{ type: 'user_input', content: [{ type: 'text', text: PANEL_REQUEST }] }],
          systemInstruction: system,
          thinkingLevel: 'low',
          ...(request.signal ? { signal: request.signal } : {}),
        },
        (delta) => drain(stream.push(delta)),
      );
      drain(stream.end());
    } catch {
      return shape;
    }
  }

  return shape;
}

/**
 * What a panel redraw asks for.
 *
 * Short, because the surface brief in the skill already says what a panel is and
 * what it may contain. This only has to say *now*.
 */
const PANEL_REQUEST =
  'Redraw this surface for where the trip stands now. Only the surface — no prose.';

/**
 * Turns an API failure into something the traveler can act on.
 *
 * "401" is not a message; "that key was rejected" is. Because the key comes from
 * the person sitting in front of the app, auth failures are the most likely
 * error here and deserve the clearest wording — which is why `GeminiError`
 * carries the sentence rather than leaving it to be reconstructed from a status
 * code at the far end.
 */
export function describeApiError(error: unknown): AgentEvent & { type: 'error' } {
  if (error instanceof GeminiError) {
    return { type: 'error', message: error.message, retryable: error.retryable };
  }
  if (error instanceof Error && error.name === 'AbortError') {
    return { type: 'error', message: 'Stopped.', retryable: false };
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


