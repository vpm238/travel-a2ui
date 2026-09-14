/**
 * The browser's half of the wire protocol.
 *
 * Two things worth knowing:
 *
 * 1. **The key never goes in a URL.** `EventSource` can only issue a GET with no
 *    custom headers, which would force the API key into a query string, where it
 *    lands in every access log between here and the Worker. So this reads the
 *    SSE stream out of a `fetch` POST body instead — more code, and the only
 *    version of this that is safe to deploy.
 *
 * 2. **A turn is cancellable.** The `AbortSignal` reaches the Worker, which
 *    stops writing; the turn itself finishes server-side so the transcript stays
 *    consistent for the next message.
 */

import type { A2uiMessage } from '@travel-a2ui/express';

export type SkillVariant = 'express-modular';
export type SurfaceKind = 'inline' | 'sidebar' | 'home';

export type AgentEvent =
  | { type: 'start'; model: string; skill: SkillVariant; surfaceId: string }
  | { type: 'text'; delta: string; round?: number }
  | { type: 'ui'; surfaceId: string; messages: A2uiMessage[]; done: boolean }
  | { type: 'ui_error'; message: string; source: string; express?: string }
  | { type: 'retry'; reason: string }
  // The stream failed part-way through and the turn is starting over on the
  // standby model. Everything said so far belongs to the abandoned attempt.
  | { type: 'restart'; reason: string }
  /**
   * A different model answered this turn, because the chosen one was busy.
   *
   * Said rather than hidden. Google's capacity spikes are real — a third of the
   * turns in one eval run came back "currently experiencing high demand" with
   * no surface at all — and the server degrades to a smaller model rather than
   * ending the conversation. A demo that quietly swaps the thing it is
   * demonstrating is a demo that lies, so the swap reaches the transcript.
   */
  | { type: 'served_by'; model: string }
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
  | { type: 'error'; message: string; retryable: boolean }
  /**
   * Where the turn's time went, in milliseconds from the request arriving.
   *
   * `firstSurface` is the one that matters: everything before it is a blank
   * space where an interface should be. `firstWord` is when prose started, and
   * `tool:<name>` is how long each lookup took.
   */
  | { type: 'timing'; ms: Record<string, number> }
  /**
   * The receipt for this turn, to be handed back with the next one.
   *
   * Opaque on purpose: where Google's copy of the conversation is, and what has
   * been decided so far. The client does not read it — it stores it and sends
   * it back — which is what lets any server instance answer any turn. Without
   * it a second instance has never heard of this conversation and starts a new
   * one with an empty trip, mid-sentence.
   */
  | {
      type: 'resume';
      interactionId?: string;
      trip?: Record<string, unknown>;
      shape?: string;
      setup?: string;
    }
  | { type: 'done'; stopReason: string | null };

/** The last turn's receipt, carried by the client and sent back unread. */
export interface Resume {
  interactionId?: string;
  trip?: Record<string, unknown>;
  shape?: string;
  /**
   * Which prompt the conversation was started against.
   *
   * The server sends this and the client used to drop it, which quietly undid
   * the point of handing the receipt over: the server then fell back to its own
   * in-memory session, so "any instance can answer any turn" was true only
   * while there was one instance. It is opaque — a hash of the stable half of
   * the prompt — and the only thing to do with it is hand it back.
   */
  setup?: string;
}

export interface ModelOption {
  id: string;
  label: string;
  note: string;
}

export interface SkillInfo {
  variant: SkillVariant;
  skills: string[];
  inferenceFormat: string;
  protocolVersion: string;
  characters: number;
}

export interface Meta {
  name: string;
  catalogId: string;
  protocolVersion: string;
  defaultModel: string;
  defaultSkill: SkillVariant;
  models: ModelOption[];
  surfaces: SurfaceKind[];
  skills: SkillInfo[];
  keyProvided: boolean;
  /** Which agent runtimes this deployment knows about. */
  backends?: BackendOption[];
  /**
   * What a Gemini Live session would be bound to right now.
   *
   * `stamp` fingerprints the catalog, the skill, the tool declarations and the
   * model — exactly what the Live API's opening `setup` frame carries, and
   * nothing that varies per session. A client that instantiated against a
   * different stamp is holding a receipt for a contract this deployment no
   * longer serves, and is asked to instantiate again.
   */
  contract?: { stamp: string; maxAgeMs: number };
  /** Which runtime answered this request. */
  runtime?: BackendId;
}

/**
 * An interaction on a surface, as A2UI defines one.
 *
 * The shape of `client_to_server.json`'s `action`: what was pressed, where, and
 * the context its bindings resolved to. Every A2UI renderer produces this
 * without being taught — which is the point of sending it instead of a sentence
 * this app made up.
 *
 * `dataModel` is the one addition, and it is opaque: the rest of the surface's
 * values, forwarded so the server can keep trip state exact without any client
 * knowing what a trip is. Leave it out and the agent still has `context`.
 */
export interface SurfaceAction {
  name: string;
  surfaceId: string;
  sourceComponentId?: string;
  timestamp?: string;
  context: Record<string, unknown>;
  dataModel?: Record<string, unknown>;
}

export interface ChatRequest {
  sessionId: string;
  /** What the traveler typed. Omitted when `action` carries the turn instead. */
  message?: string;
  /** What the traveler pressed. Omitted when they typed. */
  action?: SurfaceAction;
  surface: SurfaceKind;
  surfaceId?: string;
  skill: SkillVariant;
  /**
   * Deliberately no `model` and no `effort`.
   *
   * The server defaults both, and it is the only party that can pick one model
   * for the whole screen. When the client chose, it chose for the reply and not
   * for the panel beside it — which was hardcoded to the small model with the
   * client's choice wired in as its *fallback*. Half a choice is worse than
   * none. `/api/meta` still reports which model is answering.
   */
  /**
   * What came back on the last turn, handed straight back.
   *
   * The server keeps a copy too, but only the one instance that answered has
   * it, and Cloud Run will happily send the next turn somewhere else. The
   * client is the only party present for every turn of a conversation, so it
   * is the one that carries the thread.
   */
  resume?: Resume;
  /**
   * *When* the traveler is. Not where.
   *
   * This used to carry a timezone that the server turned into a departure
   * airport, and that was the mistake: a timezone covers a continent-slice, so
   * `America/New_York` picked JFK for someone in Atlanta, 1,211 km away, and
   * said it with a fare attached. Where they are flying from is a question the
   * agent asks now, in the surface it was drawing anyway.
   *
   * What is left is the one thing the server genuinely cannot know. It runs in
   * UTC; at 18:00 in Los Angeles it has already turned the page, so "tomorrow"
   * comes back a day late and "this Saturday" is the wrong Saturday.
   */
  client?: { today?: string; locale?: string };
}

/** What day it is where the traveler is, and what language they read. */
export function clientHints(): ChatRequest['client'] {
  try {
    return {
      // `en-CA` is the shortest honest way to get a local `YYYY-MM-DD` out of
      // the browser: `toISOString` would convert to UTC first, which is the bug
      // this exists to fix.
      today: new Date().toLocaleDateString('en-CA'),
      locale: navigator.language,
    };
  } catch {
    return undefined;
  }
}

/**
 * Which agent framework is answering.
 *
 * Two genuinely different runtimes, and that is the point being made: the
 * components, the catalog, the skills and this front end are one build, and the
 * thing running the agent loop underneath is the traveller's choice.
 *
 *   python  Gemini Interactions API, driven from the Python server this app is
 *           served from. A request/response loop on the traveller's own key,
 *           calling the travel tools directly. Typed.
 *
 *           Named `worker` until the agent loop moved off Cloudflare, and the
 *           rename was overdue: the id is what the client asks the server for,
 *           the server had already been advertising `python`, and nothing
 *           matched — so the runtime chip fell through to printing the raw id
 *           and read "worker" to anybody looking at it.
 *
 *   live    Gemini Live API, relayed through the same session Durable Object.
 *           A bidirectional audio session Google drives; the traveller can
 *           speak or type, and it answers out loud while drawing the same
 *           surfaces from the same six builders.
 *
 * They share nothing, and switching between them reloads the page: a new
 * session, an empty trip, a clean transcript. Two APIs with two conversation
 * histories is enough difference without also reasoning about which parts of a
 * half-decided trip survive the crossing.
 *
 * Two alternatives were built and removed, both worth recording because the
 * reasons are measurements rather than opinions.
 *
 * A Google-hosted Managed Agent on the Antigravity harness: creating and running
 * the agent worked, but its *sandbox* returned `Audience of an ID token must be
 * a URL or service account` for every file and code-execution call. That harness
 * reads its skills off the sandbox filesystem, so the agent ran with no contract
 * at all, and a bring-your-own-key demo has no service-account credential.
 *
 * Cloudflare Code Mode, where the model writes a script instead of calling tools:
 * built, measured, and slower. The pitch is that independent searches collapse
 * into one `Promise.all`; Gemini already issues independent calls together in a
 * single round, so a flights-and-hotels turn was two rounds either way — 5.2s
 * against 4.4s, for the sandbox start. Kept in the history, not in the product.
 */
export type BackendId = 'python' | 'live';

export interface BackendOption {
  id: BackendId;
  label: string;
  note: string;
  /** Empty means "same origin as this app". */
  origin: string;
  /**
   * Whether this framework listens.
   *
   * The microphone used to be in the composer unconditionally, and pressing it
   * quietly opened a second runtime — which made two agent frameworks look like
   * one app with a feature. The control now belongs to whichever framework
   * actually has it.
   */
  voice?: boolean;
}

/**
 * Where API calls go right now.
 *
 * Empty is same-origin. `VITE_API_ORIGIN` still works as a build-time default —
 * it is what the standalone front end uses when it is not served by the Worker
 * at all — but the picker in the header overrides it per session.
 */
let apiOrigin = (import.meta.env['VITE_API_ORIGIN'] as string | undefined)?.replace(/\/$/, '') ?? '';

export const getApiOrigin = (): string => apiOrigin;

export function setApiOrigin(origin: string): void {
  apiOrigin = origin.replace(/\/$/, '');
}

const api = (path: string) => `${apiOrigin}${path}`;

/**
 * Asks a backend who it is, without committing to it.
 *
 * The picker uses this before switching, so choosing a runtime that is not
 * running says so immediately instead of failing on the next message.
 */
export async function probeBackend(origin: string): Promise<Meta> {
  const response = await fetch(`${origin.replace(/\/$/, '')}/api/meta`, {
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as Meta;
}

export const catalogUrl = () => api('/api/catalog');

export async function fetchMeta(): Promise<Meta> {
  const response = await fetch(api('/api/meta'));
  if (!response.ok) throw new Error(`Could not load app metadata (${response.status}).`);
  return (await response.json()) as Meta;
}

/** What a warm-up hands back: the conversation, already started. */
export interface Warmed {
  interactionId?: string | null;
  setup?: string | null;
  ms?: number;
  skipped?: string;
  error?: string;
}

/**
 * Starts the conversation before the traveller has typed anything.
 *
 * The first interface takes about eight times longer than every one after it,
 * because the Interactions API is stateful and the fifteen-thousand-token system
 * instruction goes up once per conversation. Paying that against a throwaway
 * turn, while somebody is still typing, is most of it back:
 *
 *     cold     first surface 19.6s
 *     warmed   first surface 11.6s
 *     second   first surface  2.4s
 *
 * Never throws. A warm-up that did not happen costs the first turn its head
 * start and nothing else, and an error banner for a request nobody made is
 * worse than the slow turn it is warning about.
 */
export async function warmUp(apiKey: string, skill: string): Promise<Warmed> {
  try {
    const response = await fetch(api('/api/warm'), {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-goog-api-key': apiKey },
      body: JSON.stringify({ skill }),
    });
    if (!response.ok) return { error: `warm-up failed (${response.status})` };
    return (await response.json()) as Warmed;
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

export async function resetSession(sessionId: string): Promise<void> {
  await fetch(api('/api/session/reset'), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ sessionId }),
  });
}

export interface StreamOptions {
  apiKey: string;
  signal?: AbortSignal;
  onEvent: (event: AgentEvent) => void;
}

/** Sends one turn and calls `onEvent` for every event until the turn ends. */
export async function streamTurn(request: ChatRequest, options: StreamOptions): Promise<void> {
  const headers: Record<string, string> = { 'content-type': 'application/json' };
  if (options.apiKey) headers['x-goog-api-key'] = options.apiKey;

  const response = await fetch(api('/api/chat'), {
    method: 'POST',
    headers,
    body: JSON.stringify(request),
    ...(options.signal ? { signal: options.signal } : {}),
  });

  if (!response.ok || !response.body) {
    let message = `Request failed (${response.status}).`;
    let hint: string | undefined;
    try {
      const body = (await response.json()) as { error?: string; hint?: string };
      if (body.error) message = body.error;
      hint = body.hint;
    } catch {
      /* the body was not JSON; the status line is all we have */
    }
    options.onEvent({
      type: 'error',
      message: hint ? `${message} ${hint}` : message,
      retryable: response.status >= 500 || response.status === 429,
    });
    return;
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;

      // SSE frames are separated by a blank line. Anything after the last one
      // is a partial frame — keep it for the next chunk.
      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf('\n\n');

        const payload = frame
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart())
          .join('\n');
        if (!payload) continue;

        try {
          options.onEvent(JSON.parse(payload) as AgentEvent);
        } catch {
          /* a frame we cannot parse is not worth killing the turn over */
        }
      }
    }
  } catch (error) {
    if ((error as Error).name === 'AbortError') return;
    options.onEvent({
      type: 'error',
      message: error instanceof Error ? error.message : String(error),
      retryable: true,
    });
  } finally {
    reader.releaseLock();
  }
}

