/**
 * The app's state: one conversation, several surfaces, one store.
 *
 * The surfaces all share a single `SurfaceStore` because they are views of one
 * trip, not separate apps. The sidebar's budget slider and the home screen's
 * budget meter read the same data model, so moving one moves the other without
 * a round trip — which is the behaviour you would expect from a native app and
 * almost never get from a chat UI.
 *
 * Interactions come back as A2UI events. An event is not a side channel: it is
 * the user's next turn, phrased in the interface instead of in prose. So it goes
 * to the model as a message, with the surface's current data model attached, and
 * the conversation continues.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { SurfaceStore, type A2uiEvent } from '@travel-a2ui/renderer';

import { consumeKeyFromUrl } from './apiKey.js';

/**
 * The trip, as far as this client is concerned: whatever the server sent.
 *
 * Deliberately opaque. The client used to import the real field list and the
 * planner from the trip package and decide for itself when a panel was stale;
 * that logic moved to the server so a Flutter or Swift client would get a
 * panel too, and the imports outlived it — `TRIP_KEYS` and `plan` were still
 * being pulled in and never called. Naming the shape here is the honest
 * version: this is a renderer, and it does not know what a trip is.
 */
export type Trip = Record<string, unknown>;
import { instantiateLive, startCall, type VoiceCall } from './voice.js';
import {
  clientHints,
  fetchMeta,
  getApiOrigin,
  probeBackend,
  resetSession,
  setApiOrigin,
  streamTurn,
  type AgentEvent,
  type BackendId,
  type Meta,
  type SkillVariant,
  type SurfaceAction,
  type SurfaceKind,
} from './api.js';

const API_KEY = 'travel-a2ui:key';
const PREFS_KEY = 'travel-a2ui:prefs';
const BACKEND_KEY = 'travel-a2ui:backend';
const LIVE_KEY = 'travel-a2ui:live';

/**
 * What the app remembers about instantiating the Live agent.
 *
 * The Live API has no agent object to look up, so the client keeps the receipt:
 * which contract the handshake bound to, which model answered, and when.
 */
interface LiveRecord {
  contract: string;
  model: string;
  at: number;
}

export type LiveStatus =
  /** No key yet, or never instantiated. */
  | 'absent'
  /** Handshaking now. */
  | 'instantiating'
  /** Bound to the contract this deployment is currently serving. */
  | 'ready'
  /** Bound to something this deployment no longer serves, or bound too long ago. */
  | 'stale'
  /** The handshake was refused — usually the key. */
  | 'failed';

function readLiveRecord(): LiveRecord | null {
  try {
    const stored = readStored(LIVE_KEY);
    if (!stored) return null;
    const parsed = JSON.parse(stored) as LiveRecord;
    return typeof parsed?.contract === 'string' ? parsed : null;
  } catch {
    return null;
  }
}

export interface ToolCall {
  name: string;
  input: unknown;
  result?: unknown;
  isError?: boolean;
}

/**
 * One piece of an assistant turn, in the order it arrived.
 *
 * A turn is not "some text, then a surface" — a model says a sentence, draws,
 * and says another sentence, and rendering all the prose above all the UI puts
 * "want me to hold one?" before the thing being held. So a turn is a sequence.
 */
export type TurnPart =
  /** `round` is the tool round this prose came from — see `withText`. */
  | { kind: 'text'; text: string; round: number }
  | { kind: 'surface'; surfaceId: string };

export interface Turn {
  id: string;
  role: 'user' | 'assistant';
  /** For a user turn, what they said. For an assistant turn, see `parts`. */
  text: string;
  parts: TurnPart[];
  tools: ToolCall[];
  error?: string;
  /** Set while the agent is rewriting a block that did not compile. */
  retrying?: string;
  streaming: boolean;
  /** True when this user turn came from tapping the interface, not typing. */
  fromSurface?: boolean;
  /**
   * Where this turn's time went, in milliseconds. Arrives once, at the end.
   *
   * Kept per turn rather than as one running total because the question it
   * answers — "why did that take so long" — is always about a particular turn.
   */
  timing?: Record<string, number>;
}

/**
 * Appends a text delta to the open text part, or starts one.
 *
 * A new tool round starts a new part even when the last part is text. The model
 * says a sentence, calls a tool, then says another; those are two paragraphs,
 * and concatenating them produces "…anything.Nothing nonstop is showing" —
 * which reads as a typo rather than as two thoughts.
 */
function withText(parts: TurnPart[], delta: string, round: number): TurnPart[] {
  const last = parts[parts.length - 1];
  if (last?.kind === 'text' && last.round === round) {
    return [...parts.slice(0, -1), { kind: 'text', text: last.text + delta, round }];
  }
  return [...parts, { kind: 'text', text: delta, round }];
}

/**
 * The surfaces that live somewhere of their own.
 *
 * The panel and the home screen are standing surfaces: one each, replaced as
 * the trip moves, drawn by the view that owns them. The conversation is a feed
 * of `inline-N` cards.
 */
const STANDING = new Set(['sidebar', 'home']);

/**
 * Records a surface once; later events for it only update the store.
 *
 * A turn usually touches three surfaces — the card it drew, and the two
 * standing panels the server refreshed from the trip — and this attached all of
 * them to the chat bubble. So the panel was rendered twice: once where it
 * lives, and again in the middle of the conversation, under the question the
 * traveler was still answering, with its own Change buttons.
 *
 * It read exactly like the model drawing the trip summary inline, which is what
 * it was mistaken for. It was the client, filing a panel refresh as
 * conversation.
 */
function withSurface(parts: TurnPart[], surfaceId: string): TurnPart[] {
  if (STANDING.has(surfaceId)) return parts;
  if (parts.some((part) => part.kind === 'surface' && part.surfaceId === surfaceId)) return parts;
  return [...parts, { kind: 'surface', surfaceId }];
}

export interface Usage {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
  /** Billed as output, and usually the largest share of a Flash turn. */
  thoughtTokens: number;
  turns: number;
}

export interface Prefs {
  model: string;
  skill: SkillVariant;
  effort: 'low' | 'medium' | 'high';
}

const EMPTY_USAGE: Usage = {
  inputTokens: 0,
  outputTokens: 0,
  cacheReadTokens: 0,
  cacheWriteTokens: 0,
  thoughtTokens: 0,
  turns: 0,
};

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* private browsing, or storage disabled — the app still works this session */
  }
}

function newSessionId(): string {
  return `s_${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36)}`;
}

/**
 * Trip facts live at `/trip` in every surface's data model — and the server
 * puts them there.
 *
 * This file used to hold a list of travel field names and two functions that
 * copied values between surfaces with it: `seedTrip` filled a new surface as it
 * arrived, `syncTrip` pushed changes into the standing panels. That worked, and
 * it made the web app the only client that could behave correctly, because the
 * behaviour lived in the client rather than in the protocol.
 *
 * The server does it now, in A2UI's own words: `dataModel` on the surface it
 * creates, `updateDataModel` for the panels already on screen. Both are messages
 * every renderer applies, so an iOS client gets pre-filled controls and a live
 * panel with no travel-specific code at all — and this app forgets what a trip
 * is, which is the point.
 */

/**
 * Read per turn, not once.
 *
 * The timezone and locale do not change while the tab is open, and this was
 * a module constant for that reason. Coordinates do change — they arrive the
 * moment the traveler agrees to share them — and a constant read at module
 * load would have captured the answer from before they were asked, so the
 * permission prompt would have appeared, been granted, and changed nothing.
 */

/**
 * An interaction, in the shape A2UI already defines for one.
 *
 * This used to be a sentence — `[interface] search_flights (origin: "JFK")` —
 * assembled here and parsed by nobody. It looked harmless and was not: a
 * synthetic prose format is an application protocol layered on top of A2UI, and
 * a Swift or Kotlin renderer has no idea it exists. What every A2UI renderer
 * *does* already do is resolve an action's bound context and hand it over,
 * which is this, with no host in the middle inventing anything.
 *
 * `context` is the answer the traveler is sending. `dataModel` is the rest of
 * the surface, sent opaquely so the server can keep the trip exact without any
 * client knowing what a trip is; a generic client that omits it still works,
 * because the agent reads `context`.
 */
/**
 * How an interaction reads in the transcript.
 *
 * Display only. The wire carries the action; this is so the conversation has a
 * line where the traveler's turn was, rather than a gap followed by an answer
 * to a question nobody can see being asked.
 */
function describeForTranscript(action: SurfaceAction): string {
  const said = Object.entries(action.context)
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => `${key}: ${JSON.stringify(value)}`)
    .join(', ');
  const name = action.name.replace(/_/g, ' ');
  return said ? `${name} — ${said}` : name;
}

function actionFrom(event: A2uiEvent): SurfaceAction {
  return {
    name: event.name,
    surfaceId: event.surfaceId,
    ...(event.source?.id ? { sourceComponentId: event.source.id } : {}),
    timestamp: new Date().toISOString(),
    context: event.context ?? {},
    dataModel: event.dataModel ?? {},
  };
}

export function useAgent() {
  const store = useMemo(() => new SurfaceStore(), []);

  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  // A key in the URL wins over a stored one and is consumed on the first read,
  // before anything else can see it in `location`.
  const [urlKey] = useState(() => consumeKeyFromUrl());
  const [apiKey, setApiKeyState] = useState<string>(() => urlKey?.key ?? readStored(API_KEY) ?? '');
  /**
   * A fresh conversation on every load, deliberately not persisted.
   *
   * The trip lives server-side keyed by this id, so a new id is a clean slate:
   * no transcript, no half-decided destination from yesterday, no surface
   * referring to a flight nobody remembers choosing. Reloading is how a person
   * says "start over", and honouring that is worth more here than resuming —
   * this is a demo of an interface, not a booking system with a saved cart.
   *
   * The API key does persist. Losing that on reload would be a different and
   * much more annoying kind of forgetting.
   */
  const [sessionId, setSessionId] = useState<string>(newSessionId);

  const [prefs, setPrefsState] = useState<Prefs>(() => {
    try {
      const stored = readStored(PREFS_KEY);
      if (stored) return { ...JSON.parse(stored) } as Prefs;
    } catch {
      /* fall through to defaults */
    }
    return { model: 'gemini-3.8-flash', skill: 'express-monolithic', effort: 'low' };
  });

  /**
   * Which agent runtime is answering, and where it lives.
   *
   * Stored per browser rather than per deployment: the choice is about what you
   * want to watch run, and it should survive a reload. `origin` is applied to
   * the api module immediately, before the first request goes out.
   */
  const [backend, setBackendState] = useState<{ id: BackendId; origin: string }>(() => {
    try {
      const stored = readStored(BACKEND_KEY);
      if (stored) {
        const parsed = JSON.parse(stored) as { id: BackendId; origin: string };
        setApiOrigin(parsed.origin ?? '');
        return parsed;
      }
    } catch {
      /* fall through to the Worker, which is always there */
    }
    return { id: 'worker', origin: getApiOrigin() };
  });
  const [backendError, setBackendError] = useState<string | null>(null);

  const [turns, setTurns] = useState<Turn[]>([]);
  const [trip, setTrip] = useState<Trip>({});
  const [usage, setUsage] = useState<Usage>(EMPTY_USAGE);
  const [busy, setBusy] = useState(false);
  const [liveSurface, setLiveSurface] = useState<SurfaceKind | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  // Read inside callbacks that must not be recreated on every keystroke.
  const prefsRef = useRef(prefs);
  prefsRef.current = prefs;
  const keyRef = useRef(apiKey);
  keyRef.current = apiKey;
  const backendRef = useRef(backend.origin);
  backendRef.current = backend.origin;

  /**
   * Which framework is answering, readable from inside callbacks.
   *
   * `send` is memoised on things that rarely change; reading the choice from a
   * ref keeps a switch mid-conversation from needing a new closure.
   */
  const frameworkRef = useRef(backend.id);
  frameworkRef.current = backend.id;

  /**
   * Hands a typed line to the Live session, opening it if it is not open.
   *
   * A forward reference, because the voice block is defined below `send` and
   * `send` is what needs it. The alternative was routing typed text to the
   * Interactions API while the traveller had chosen Live — which is the exact
   * confusion this switch exists to remove.
   */
  const speakRef = useRef<((text: string) => Promise<boolean>) | null>(null);
  // Read while a turn is streaming, where `trip` in the closure is stale.
  const tripRef = useRef(trip);
  tripRef.current = trip;

  // Persist a URL-supplied key so a reload does not lose it.
  useEffect(() => {
    if (urlKey?.key) writeStored(API_KEY, urlKey.key);
  }, [urlKey]);

  useEffect(() => {
    fetchMeta()
      .then((loaded) => {
        setMeta(loaded);
        setPrefsState((current) => ({
          ...current,
          model: current.model || loaded.defaultModel,
          skill: current.skill || loaded.defaultSkill,
        }));
      })
      .catch((error: unknown) =>
        setMetaError(error instanceof Error ? error.message : String(error)),
      );
  }, []);

  const setApiKey = useCallback((value: string) => {
    const trimmed = value.trim();
    setApiKeyState(trimmed);
    writeStored(API_KEY, trimmed || null);
  }, []);

  /**
   * Switches framework, which starts the demo over.
   *
   * The frameworks share nothing. They are different APIs with different
   * conversation histories, and carrying a half-decided trip from one into the
   * other buys a subtlety nobody asked for — "they share the trip but not the
   * transcript" is a sentence a demo should not have to explain. So the choice
   * is written down and the page reloads, which is already how this app starts
   * over: a reload mints a new session id, and the trip lives server-side under
   * it, so the new framework opens on a clean slate.
   *
   * Reloading rather than unwinding state in place is the point. There is no
   * order of `setTrip`, `store.reset`, `setTurns` and `setUsage` that is
   * obviously complete, and the one that is missed shows up as a surface from
   * the previous framework sitting in the new one.
   *
   * The API key survives, because it is in localStorage and losing it on every
   * switch would be a different and much more annoying kind of forgetting.
   *
   * Probing first still matters: a custom origin that is not running says so
   * here, with the URL you gave it, rather than after a reload into a blank app.
   */
  const setBackend = useCallback(async (id: BackendId, origin: string): Promise<boolean> => {
    const clean = origin.replace(/\/$/, '');
    setBackendError(null);
    try {
      await probeBackend(clean || window.location.origin);
      writeStored(BACKEND_KEY, JSON.stringify({ id, origin: clean }));
      // Release the microphone before the page goes, so the recording
      // indicator does not linger through the reload.
      callRef.current?.hangUp();
      window.location.reload();
      return true;
    } catch (error) {
      setBackendError(
        `${clean || 'this origin'} did not answer (${error instanceof Error ? error.message : String(error)}).`,
      );
      return false;
    }
  }, []);

  const setPrefs = useCallback((patch: Partial<Prefs>) => {
    setPrefsState((current) => {
      const next = { ...current, ...patch };
      writeStored(PREFS_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const patchTurn = useCallback((id: string, patch: Partial<Turn> | ((turn: Turn) => Partial<Turn>)) => {
    setTurns((current) =>
      current.map((turn) =>
        turn.id === id ? { ...turn, ...(typeof patch === 'function' ? patch(turn) : patch) } : turn,
      ),
    );
  }, []);

  /**
   * One turn, whether the traveler typed it or pressed it.
   *
   * A string is a typed message. A `SurfaceAction` is an interaction, sent as
   * the A2UI action it already is; the transcript still shows a sentence, but
   * that sentence is written *here for display* and never goes on the wire.
   */
  const send = useCallback(
    async (
      input: string | SurfaceAction,
      options: {
        surface?: SurfaceKind;
        surfaceId?: string;
        fromSurface?: boolean;
        /** Keep the transcript clean for background surfaces like the home screen. */
        silent?: boolean;
      } = {},
    ) => {
      const action = typeof input === 'string' ? undefined : input;
      const message = typeof input === 'string' ? input.trim() : '';
      const text = action ? describeForTranscript(action) : message;
      const surface = options.surface ?? 'inline';
      // An empty message on a standing surface is a request to draw it, and the
      // server writes the brief. Only the conversation needs something said.
      const drawing = !action && !message && surface !== 'inline';
      if ((!action && !message && !drawing) || busy) return;

      /*
       * In Live, the Live session is the conversation.
       *
       * Typing and pressing both go into it, so a session has one framework and
       * one history rather than quietly straddling two. A surface press is
       * relayed as the sentence the transcript already shows, which loses the
       * A2UI action's structure — the Live API has no equivalent to send — and
       * is the one place this switch costs something.
       *
       * `drawing` is excluded on purpose: a standing panel redraw is server-
       * driven panel mechanics rather than something the traveller said, and it
       * goes over HTTP in either framework. It reads the same shared trip, so
       * the panel stays correct; it just is not part of the spoken history.
       */
      if (frameworkRef.current === 'live' && !drawing && !options.silent) {
        const spoken = await speakRef.current?.(text);
        if (spoken) return;
        // Falling through means the call could not be opened — the microphone
        // was refused, or the key is missing. The error is already on screen.
        return;
      }

      const assistantId = `a_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;

      if (!options.silent) {
        setTurns((current) => [
          ...current,
          {
            id: `u_${assistantId}`,
            role: 'user',
            text,
            parts: [],
            tools: [],
            streaming: false,
            ...(options.fromSurface ? { fromSurface: true } : {}),
          },
          { id: assistantId, role: 'assistant', text: '', parts: [], tools: [], streaming: true },
        ]);
      }

      setBusy(true);
      setLiveSurface(surface);
      const controller = new AbortController();
      abortRef.current = controller;

      const handle = (event: AgentEvent) => {
        switch (event.type) {
          case 'start':
            break;
          case 'text':
            if (!options.silent) {
              patchTurn(assistantId, (turn) => ({
                text: turn.text + event.delta,
                parts: withText(turn.parts, event.delta, event.round ?? 0),
              }));
            }
            break;
          case 'ui':
            // A block that compiles clears any retry note: it worked.
            if (!options.silent) patchTurn(assistantId, { retrying: undefined });
            // Everything the surface should show is already in these messages:
            // the server seeds `/trip` into the surface it creates and sends
            // `updateDataModel` for the panels. Applying them is the whole job.
            store.apply(event.messages);
            if (!options.silent) {
              patchTurn(assistantId, (turn) => ({
                parts: withSurface(turn.parts, event.surfaceId),
              }));
            }
            break;
          case 'ui_error':
            // Not surfaced as an error yet: the agent gets one attempt to
            // rewrite the block, and a message that flashes red and then fixes
            // itself is worse than no message.
            break;
          case 'retry':
            if (!options.silent) patchTurn(assistantId, { retrying: event.reason });
            break;
          case 'tool':
            if (!options.silent) {
              patchTurn(assistantId, (turn) => ({
                tools: [...turn.tools, { name: event.name, input: event.input }],
              }));
            }
            break;
          case 'tool_result':
            if (!options.silent) {
              patchTurn(assistantId, (turn) => {
                const tools = [...turn.tools];
                for (let index = tools.length - 1; index >= 0; index--) {
                  if (tools[index]!.name === event.name && tools[index]!.result === undefined) {
                    tools[index] = { ...tools[index]!, result: event.result, isError: event.isError };
                    break;
                  }
                }
                return { tools };
              });
            }
            break;
          case 'trip':
            setTrip(event.trip);
            break;
          case 'timing':
            if (!options.silent) patchTurn(assistantId, { timing: event.ms });
            break;
          case 'usage':
            setUsage((current) => ({
              inputTokens: current.inputTokens + event.inputTokens,
              outputTokens: current.outputTokens + event.outputTokens,
              cacheReadTokens: current.cacheReadTokens + event.cacheReadTokens,
              cacheWriteTokens: current.cacheWriteTokens + event.cacheWriteTokens,
              thoughtTokens: current.thoughtTokens + event.thoughtTokens,
              turns: current.turns + 1,
            }));
            break;
          case 'error':
            if (options.silent) break;
            patchTurn(assistantId, { error: event.message });
            break;
          case 'done':
            if (!options.silent) patchTurn(assistantId, { streaming: false });
            break;
        }
      };

      try {
        await streamTurn(
          {
            sessionId,
            ...(action ? { action } : { message }),
            surface,
            skill: prefsRef.current.skill,
            model: prefsRef.current.model,
            effort: prefsRef.current.effort,
            ...(options.surfaceId ? { surfaceId: options.surfaceId } : {}),
            ...((): object => {
              const hints = clientHints();
              return hints ? { client: hints } : {};
            })(),
          },
          { apiKey: keyRef.current, signal: controller.signal, onEvent: handle },
        );
      } finally {
        if (!options.silent) patchTurn(assistantId, { streaming: false });
        setBusy(false);
        setLiveSurface(null);
        abortRef.current = null;
      }
    },
    [busy, patchTurn, sessionId, store],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
    setLiveSurface(null);
  }, []);

  /**
   * Wired to every surface. A *decision* is the user's next turn; an edit is not.
   *
   * An edit still lands in the surface's data model, where it stays until the
   * traveler commits — so three choices on one card are three choices, not three
   * turns against three surfaces that each forgot the last.
   */
  /**
   * Asks the server to draw a standing surface.
   *
   * The one thing a client legitimately knows that the server does not is
   * *which surface it is showing*. Everything else about a panel — when it is
   * stale, what to ask for, what may go on it — is the agent's, and used to be
   * here: the sidebar watched three trip field names and composed a prose
   * prompt ("Rebuild the panel for where the trip stands now…") to send as a
   * silent turn. That is the private protocol recommendation 4 removed from
   * form submission, rebuilt for panels, and a client that does not know to
   * send it never gets a panel at all.
   *
   * So this says only which surface, and the server decides the rest.
   */
  const drawSurface = useCallback(
    (surface: 'sidebar' | 'home', note?: string) =>
      send(note ?? '', { surface, surfaceId: surface, silent: true }),
    [send],
  );


  const handleSurfaceEvent = useCallback(
    (event: A2uiEvent) => {
      if (busy) return;

      const surface: SurfaceKind =
        event.surfaceId === 'sidebar' ? 'sidebar' : event.surfaceId === 'home' ? 'home' : 'inline';

      // The panel is read-only, so an interaction there is not an answer — it
      // is a request to re-open a decision. Deciding happens in the
      // conversation, where there is a record of it, and one place to edit a
      // value rather than two that can disagree.
      //
      // The redirection is a routing decision, not a rewrite: the same action
      // goes out, aimed at the conversation. What it *means* — release this,
      // ask me again inline — is the server's to say, in the sentence it builds
      // for the model, because that sentence is about how this agent works and
      // not about what the traveler pressed.
      void send(actionFrom(event), {
        surface: surface === 'inline' ? surface : 'inline',
        fromSurface: true,
      });
    },
    [busy, send],
  );

  const reset = useCallback(async () => {
    abortRef.current?.abort();
    await resetSession(sessionId).catch(() => undefined);
    setSessionId(newSessionId());
    setTurns([]);
    setTrip({});
    setUsage(EMPTY_USAGE);
    store.clear();
  }, [sessionId, store]);

  // ------------------------------------------------------------- voice
  //
  // A call is the same conversation by another route: the relay runs in the
  // same Durable Object, so the trip it changes is this trip, and the surfaces
  // it draws land in this store. Nothing here knows what a flight is.

  /**
   * Adds to the transcript as a call goes on.
   *
   * Transcription arrives in fragments rather than whole sentences, so a run of
   * them from the same speaker is glued into one turn — otherwise a sentence
   * becomes six bubbles. A surface always opens a new one.
   */
  const appendVoiceTurn = useCallback(
    (entry:
      | { kind: 'text'; text: string; who: 'you' | 'agent' }
      | { kind: 'surface'; surfaceId: string }) => {
      setTurns((current) => {
        const last = current[current.length - 1];

        if (entry.kind === 'surface') {
          if (last?.role === 'assistant') {
            const parts = withSurface(last.parts, entry.surfaceId);
            return [...current.slice(0, -1), { ...last, parts }];
          }
          return [
            ...current,
            {
              id: `voice-${current.length}`,
              role: 'assistant',
              text: '',
              parts: [{ kind: 'surface', surfaceId: entry.surfaceId }],
              tools: [],
              streaming: false,
            },
          ];
        }

        const role = entry.who === 'you' ? 'user' : 'assistant';
        if (last?.role === role && (last.parts.at(-1)?.kind ?? 'text') === 'text') {
          const parts = withText(last.parts, entry.text, 0);
          return [...current.slice(0, -1), { ...last, text: last.text + entry.text, parts }];
        }
        return [
          ...current,
          {
            id: `voice-${current.length}`,
            role,
            text: entry.text,
            parts: role === 'user' ? [] : [{ kind: 'text', text: entry.text, round: 0 }],
            tools: [],
            streaming: false,
            ...(role === 'user' ? { fromSurface: false } : {}),
          },
        ];
      });
    },
    [],
  );

  /* ------------------------------------------------- instantiating Live */

  const [liveRecord, setLiveRecord] = useState<LiveRecord | null>(() => readLiveRecord());
  const [liveBusy, setLiveBusy] = useState(false);
  const [liveError, setLiveError] = useState<string | null>(null);

  /**
   * Whether the stored instantiation still describes this deployment.
   *
   * Two ways to go stale, and they answer different questions. The stamp moving
   * means the contract itself changed — a component added, a skill rewritten,
   * a tool signature altered — and a session bound to the old one would compose
   * against a catalog that is gone. The age is a backstop for what a stamp
   * cannot see: a key revoked upstream, a quota since exhausted.
   */
  const liveStatus: LiveStatus = (() => {
    if (liveBusy) return 'instantiating';
    if (liveError) return 'failed';
    if (!liveRecord || !apiKey) return 'absent';
    const stamp = meta?.contract?.stamp;
    if (stamp && liveRecord.contract !== stamp) return 'stale';
    const maxAge = meta?.contract?.maxAgeMs ?? 24 * 60 * 60 * 1000;
    if (Date.now() - liveRecord.at > maxAge) return 'stale';
    return 'ready';
  })();

  const runInstantiate = useCallback(async (): Promise<boolean> => {
    if (!keyRef.current) {
      setLiveError('Add your Gemini key first.');
      return false;
    }
    setLiveBusy(true);
    setLiveError(null);
    try {
      const bound = await instantiateLive({
        origin: backendRef.current,
        sessionId,
        apiKey: keyRef.current,
      });
      const record: LiveRecord = { ...bound, at: Date.now() };
      writeStored(LIVE_KEY, JSON.stringify(record));
      setLiveRecord(record);
      return true;
    } catch (error) {
      setLiveError(error instanceof Error ? error.message : String(error));
      return false;
    } finally {
      setLiveBusy(false);
    }
  }, [sessionId]);

  /**
   * Instantiate as soon as there is a key and a reason to.
   *
   * "Add your key and it says instantiating" is the intended experience, so
   * this runs on its own rather than waiting to be pressed. It is keyed on the
   * thing being instantiated against, so a redeploy that moves the stamp
   * re-runs it exactly once — and a failure does not, because `liveError` puts
   * the status in `failed` and the button below is then the way back.
   */
  const attempted = useRef<string | null>(null);
  useEffect(() => {
    if (backend.id !== 'live' || !apiKey) return;
    if (liveStatus !== 'absent' && liveStatus !== 'stale') return;
    const target = `${apiKey.slice(-6)}:${meta?.contract?.stamp ?? ''}`;
    if (attempted.current === target) return;
    attempted.current = target;
    void runInstantiate();
  }, [backend.id, apiKey, liveStatus, meta?.contract?.stamp, runInstantiate]);

  const [call, setCall] = useState<VoiceCall | null>(null);
  /** The same call, readable synchronously — `setCall` lands a tick too late. */
  const callRef = useRef<VoiceCall | null>(null);
  const [listening, setListening] = useState(false);
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);

  const hangUp = useCallback(() => {
    call?.hangUp();
    callRef.current = null;
    setCall(null);
    setListening(false);
    setAgentSpeaking(false);
  }, [call]);

  const startVoice = useCallback(async () => {
    if (call) return hangUp();
    if (!keyRef.current) {
      setVoiceError('Add your Gemini key first.');
      return;
    }
    setVoiceError(null);
    try {
      const started = await startCall({
        origin: backendRef.current,
        sessionId,
        apiKey: keyRef.current,
        onSpeakingChange: setAgentSpeaking,
        onEvent: (event) => {
          switch (event.type) {
            case 'ui':
              store.apply(event.messages as never);
              // Voice surfaces join the transcript like any other, so the
              // record of a call reads the same as the record of a chat.
              appendVoiceTurn({ kind: 'surface', surfaceId: event.surfaceId });
              break;
            case 'transcript':
              appendVoiceTurn({ kind: 'text', text: event.text, who: event.who });
              break;
            case 'trip':
              setTrip(event.trip);
              break;
            case 'error':
              setVoiceError(event.message);
              break;
            default:
              break;
          }
        },
      });
      callRef.current = started;
      setCall(started);
      setListening(true);
      return started;
    } catch (error) {
      setVoiceError(error instanceof Error ? error.message : String(error));
    }
  }, [call, hangUp, sessionId, store]);

  /**
   * Types into the Live session, opening it first if nothing is open.
   *
   * `startVoice` toggles, so this only calls it when there is demonstrably no
   * call — otherwise a typed line would hang up on the traveller.
   */
  const speak = useCallback(
    async (text: string): Promise<boolean> => {
      const existing = callRef.current ?? (await startVoice()) ?? null;
      if (!existing) return false;
      existing.say(text);
      return true;
    },
    [startVoice],
  );
  speakRef.current = speak;

  return {
    store,
    /** True when the chosen framework has a microphone. */
    canSpeak: (meta?.backends ?? []).find((entry) => entry.id === backend.id)?.voice === true,
    /**
     * Instantiating the Live agent: a real handshake that binds the catalog,
     * the skill and the tools, and reports what it bound to.
     */
    live: {
      status: liveStatus,
      error: liveError,
      model: liveRecord?.model ?? null,
      boundAt: liveRecord?.at ?? null,
      contract: liveRecord?.contract ?? null,
      instantiate: runInstantiate,
    },
    voice: {
      listening,
      speaking: agentSpeaking,
      error: voiceError,
      start: startVoice,
      hangUp,
      say: (text: string) => call?.say(text),
    },
    meta,
    metaError,
    apiKey,
    /** Set when the key arrived in a query string, which the server logged. */
    keyWasExposed: Boolean(urlKey?.exposed),
    setApiKey,
    prefs,
    setPrefs,
    backend,
    setBackend,
    backendError,
    sessionId,
    turns,
    trip,
    usage,
    busy,
    liveSurface,
    send,
    drawSurface,
    stop,
    reset,
    handleSurfaceEvent,
  };
}

export type Agent = ReturnType<typeof useAgent>;
