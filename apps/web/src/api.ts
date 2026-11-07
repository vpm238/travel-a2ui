/**
 * The browser's half of the transport (`docs/transport.md`).
 *
 * A turn is a POST to `/api/chat` carrying what the traveller typed, the A2UI
 * v1.0 renderer-to-agent messages (`a2ui`) and the renderer's metadata, and
 * answered as server-sent events carrying A2UI v1.0 agent-to-renderer
 * messages. Two things worth knowing:
 *
 * 1. **The key never goes in a URL.** `EventSource` can only issue a GET with no
 *    custom headers, which would put the API key in a query string, where it
 *    lands in every access log on the way. So this reads the SSE stream out of
 *    a `fetch` POST body instead.
 *
 * 2. **A turn is cancellable.** The `AbortSignal` reaches the server, which
 *    stops writing; the turn itself finishes server-side so the transcript stays
 *    consistent for the next message.
 */

import type { ActionMessage, ActionPayload, RendererErrorMessage } from '@a2ui/web_core/v1_0';

/** What a request carries on the renderer's behalf (`metadata`). */
export interface RendererMetadata {
  a2uiRendererCapabilities: unknown;
  a2uiRendererDataModel?: unknown;
}

/** A press as the v1.0 renderer-to-agent message it is. */
export function actionMessage(action: ActionPayload): ActionMessage {
  return {
    version: '1.0',
    action: {
      name: action.name,
      surfaceId: action.surfaceId,
      sourceComponentId: action.sourceComponentId,
      timestamp: action.timestamp || new Date().toISOString(),
      context: action.context ?? {},
      ...(action.userMessage ? { userMessage: action.userMessage } : {}),
    },
  };
}

/** One A2UI message, as the server sends it; `@a2ui/web_core` validates it on arrival. */
type A2uiMessage = Record<string, unknown>;

export type SkillVariant = 'express-modular';
export type SurfaceKind = 'inline' | 'sidebar' | 'home';

export type AgentEvent =
  | { type: 'start'; model: string; surfaceId: string }
  | { type: 'text'; delta: string; round?: number }
  | { type: 'ui'; surfaceId: string; messages: A2uiMessage[]; done: boolean }
  | { type: 'ui_error'; message: string; source: string; express?: string }
  /** Something in the request the server could not read, such as a malformed action. */
  | { type: 'warning'; message: string }
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
      setup?: string;
    }
  | { type: 'done'; stopReason: string | null };

/** The last turn's receipt, carried by the client and sent back unread. */
export interface Resume {
  interactionId?: string;
  trip?: Record<string, unknown>;
  /**
   * Which prompt the conversation was started against.
   *
   * Handed back on the next turn, so any server instance can answer it rather
   * than only the one holding the session in memory. It is opaque — a hash of the stable half of
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
  /**
   * Where a first visit's sample trip is, relative to the page, or null for
   * none. A recording of a real conversation with this agent, replayed through
   * the same handler as a live turn — see `tools/sample/record.py`.
   */
  sampleTrip?: string | null;
  /** What an empty conversation offers to say first, shared by every client. */
  openers?: string[];
  /**
   * The deployment's Google Maps key, for loading the Maps JavaScript API.
   *
   * Public on purpose — a Maps key is restricted by HTTP referrer rather
   * than kept secret, and the page is what loads the library. Empty when
   * the deployment has none, and then maps say so instead of failing.
   */
  mapsApiKey?: string;
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
 * A press, as the app holds it: the A2UI v1.0 action body.
 *
 * On the wire it goes as `{version: "1.0", action}` (`actionMessage` in
 * `surfaces.ts`); what the traveller set on the surface goes separately, in
 * the request's `a2uiRendererDataModel`. `dataModel` is local, for naming the
 * press in the transcript, and is never sent.
 */
export type SurfaceAction = ActionMessage['action'] & { dataModel?: Record<string, unknown> };

export interface ChatRequest {
  sessionId: string;
  /** What the traveler typed. Omitted when a press carries the turn instead. */
  message?: string;
  /** A2UI v1.0 renderer-to-agent messages: the press, and any renderer errors. */
  a2ui?: Array<ActionMessage | RendererErrorMessage>;
  /** `a2uiRendererCapabilities` and `a2uiRendererDataModel`, on every request. */
  metadata?: RendererMetadata;
  /** The surface ids this renderer holds. */
  surfaces?: string[];
  surface: SurfaceKind;
  /**
   * No `model` and no `effort`: the server picks, and picks the same model for
   * the answer and for the panel beside it. `/api/meta` reports which.
   */
  /**
   * What came back on the last turn, handed straight back. The client is the
   * only party present for every turn, so it carries the thread, and any
   * server instance can answer the next one.
   */
  resume?: Resume;
  /**
   * *When* the traveler is, not where: the server runs in UTC, and "tomorrow"
   * is the traveller's tomorrow. Where they fly from is asked, never inferred.
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
 * Which agent runtime is answering.
 *
 *   python  Gemini Interactions API, driven from the Python server this app is
 *           served from: a request/response loop calling the travel tools.
 *   live    Gemini Live API, relayed through the same server: speak or type,
 *           and it answers out loud while drawing the same surfaces through
 *           the same A2UI processor.
 *
 * Switching between them reloads the page: a new session and a clean
 * transcript.
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
   * The microphone belongs to whichever framework actually has one, rather
   * than to the composer: voice is a second runtime, not a feature.
   */
  voice?: boolean;
}

/**
 * Where API calls go right now. Empty is same-origin; `VITE_API_ORIGIN` sets a
 * build-time default, and the picker in the header overrides it per session.
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

/** A surface's messages as Express, by the A2UI SDK's own decompiler on the server. */
export async function decompile(messages: unknown[]): Promise<string> {
  const response = await fetch(api('/api/express'), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ messages }),
  });
  if (!response.ok) throw new Error(`decompile failed: ${response.status}`);
  const body = (await response.json()) as { express?: string };
  return body.express ?? '';
}

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
export async function warmUp(apiKey: string): Promise<Warmed> {
  try {
    const response = await fetch(api('/api/warm'), {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-goog-api-key': apiKey },
      body: JSON.stringify({}),
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

/** A recorded conversation: what was said or pressed, and the events that answered it. */
export interface SampleRecording {
  recorded: string;
  model?: string;
  turns: Array<{ message?: string; action?: SurfaceAction; events: AgentEvent[] }>;
}

/**
 * The sample trip, or null when there is none to show.
 *
 * Fetched from the page's own origin rather than the API's: it ships with the
 * web build, next to `index.html`, whichever backend answers turns.
 */
export async function fetchSampleTrip(path: string): Promise<SampleRecording | null> {
  try {
    const response = await fetch(path, { cache: 'no-cache' });
    if (!response.ok) return null;
    const recording = (await response.json()) as SampleRecording;
    return Array.isArray(recording?.turns) && recording.turns.length > 0 ? recording : null;
  } catch {
    return null;
  }
}
