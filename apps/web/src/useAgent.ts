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
 * that logic moved to the server so the Flutter client would get a
 * panel too, and the imports outlived it — `TRIP_KEYS` and `plan` were still
 * being pulled in and never called. Naming the shape here is the honest
 * version: this is a renderer, and it does not know what a trip is.
 */
export type Trip = Record<string, unknown>;
import { instantiateLive, startVoice as openVoice, type VoiceSession } from './voice.js';
import {
  warmUp,
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
  type Resume,
  type SkillVariant,
  type SurfaceAction,
  type SurfaceKind,
} from './api.js';

const API_KEY = 'travel-a2ui:key';
// Bumped when a default changes in a way a stored preference would hide. The
// effort default moved from `low` to `minimal` — worth about thirteen seconds a
// turn — and anyone who had already loaded the app once would have kept `low`
// forever without ever having chosen it.
const PREFS_KEY = 'travel-a2ui:prefs2';
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
  /** The model that actually answered, when the chosen one was busy. */
  servedBy?: string;
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

/**
 * What the traveller actually chooses.
 *
 * The model and the thinking effort used to be in here and are not any more.
 * They were offered as a choice the app did not keep — the answer used what you
 * picked and the panel beside it was hardcoded to the small model — and the
 * stored default meant a first visit ran the *conversation* on Flash Lite while
 * `/api/meta` said the default was Flash 3.8. Sending nothing lets the server
 * decide, which it was always doing anyway for half the screen.
 */
/**
 * How ready the agent is to answer quickly.
 *
 * `cold` is not broken — it is a conversation that has not been started yet,
 * and a first message sent while cold works exactly as it always did, about
 * eight times slower to draw. See `warm`.
 */
export type Warmth = 'cold' | 'warming' | 'ready' | 'failed';

export interface Prefs {
  skill: SkillVariant;
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
 * every renderer applies, so the Flutter client gets pre-filled controls and a live
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
 * a second renderer has no idea it exists. What every A2UI renderer
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

  /**
   * The last turn's receipt, carried by this tab and handed back unread.
   *
   * The server keeps its own copy keyed by `sessionId`, but *only the instance
   * that answered* has it, and the point of Cloud Run is that the next turn may
   * land somewhere else. That instance has never heard of this conversation:
   * without the receipt it starts a new one with an empty trip, mid-sentence,
   * with the half-planned trip still on screen.
   *
   * The client is the only party present for every turn, so the client is what
   * carries the thread. It never reads this — it is where Google's copy of the
   * conversation lives plus what has been decided — which is what keeps the
   * browser from needing to know what a trip is.
   *
   * A ref, not state: it is read where a request is built and rendering nothing
   * depends on it, so a re-render would be pure waste.
   */
  const resumeRef = useRef<Resume | undefined>(undefined);

  const [prefs, setPrefsState] = useState<Prefs>(() => {
    try {
      const stored = readStored(PREFS_KEY);
      if (stored) return { ...JSON.parse(stored) } as Prefs;
    } catch {
      /* fall through to defaults */
    }
    return { skill: 'express-modular' };
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
        const parsed = JSON.parse(stored) as { id: BackendId | 'worker'; origin: string };
        setApiOrigin(parsed.origin ?? '');
        // `worker` is what this runtime was called before the agent loop moved
        // off Cloudflare. Somebody who used the app then still has it in local
        // storage, and an id the server no longer advertises matches nothing —
        // which showed up as a runtime chip reading "worker" rather than a
        // label. Read the old spelling, keep the new one.
        const id: BackendId = parsed.id === 'worker' ? 'python' : parsed.id;
        return { ...parsed, id };
      }
    } catch {
      /* fall through to the server this page came from, which is always there */
    }
    return { id: 'python', origin: getApiOrigin() };
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
      sessionRef.current?.close();
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
        // Falling through means the microphone could not be opened — it
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
          case 'served_by':
            if (!options.silent) patchTurn(assistantId, { servedBy: event.model });
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
          case 'resume':
            // Kept, not read. See `resumeRef`.
            resumeRef.current = {
              interactionId: event.interactionId,
              trip: event.trip,
              shape: event.shape,
              // Carried rather than dropped. Without it the server falls back
              // to its own session, and the claim that the client holds the
              // thread is only true while there is one server.
              setup: event.setup,
            };
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
            // The traveler's answer is finished, so the composer unlocks here
            // rather than when the stream closes. What can still arrive after
            // this is the standing panels, which the server rebuilds with a
            // second model call — worth a few seconds of somebody *not*
            // waiting, because nobody is looking at the sidebar while they
            // read the card they just asked for.
            if (!options.silent) patchTurn(assistantId, { streaming: false });
            setBusy(false);
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
            // No model and no effort: the server picks, and picks the same one
            // for the answer and for the panel beside it.
            ...(options.surfaceId ? { surfaceId: options.surfaceId } : {}),
            ...(resumeRef.current ? { resume: resumeRef.current } : {}),
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

  /**
   * Starts the conversation before the traveller finishes typing.
   *
   * Fired on the first touch of the composer rather than on page load, and that
   * is the whole design: it is the moment somebody is about to type, several
   * seconds before they are done, and it costs nothing for the visitor who
   * reads the page and leaves.
   *
   * What it buys, measured (`tools/eval/latency.py`): the first interface
   * arrives in about 11.6 s instead of 19.6 s, and the turn finishes in 13.5 s
   * instead of 29.4 s. The Interactions API is stateful, so the fifteen
   * thousand tokens of prompt go up once per conversation — this just moves
   * "once" to a moment nobody is watching.
   *
   * Once per conversation. `reset` clears the flag with the receipt, because a
   * new conversation is cold again.
   */
  const warmedRef = useRef(false);
  const [warmth, setWarmth] = useState<Warmth>('cold');

  const warm = useCallback(async () => {
    if (warmedRef.current || !keyRef.current) return;
    // Set before the request, not after: a keystroke and the page-load effect
    // landing in the same tick would otherwise start two conversations.
    warmedRef.current = true;
    setWarmth('warming');
    const warmed = await warmUp(keyRef.current, prefsRef.current.skill);
    if (warmed.interactionId) {
      // Only if nothing has happened since. Somebody who typed fast enough to
      // finish a real turn already holds a better receipt than this one.
      if (!resumeRef.current) {
        resumeRef.current = {
          interactionId: warmed.interactionId,
          setup: warmed.setup ?? undefined,
        };
      }
      setWarmth('ready');
      return;
    }
    // Failed, or skipped for want of a key. Either way it can be tried again,
    // and the only cost of never trying is a slow first turn.
    warmedRef.current = false;
    setWarmth(warmed.skipped ? 'cold' : 'failed');
  }, []);

  /**
   * Warm as soon as there is a key, rather than waiting to be asked.
   *
   * The button exists for when this has not happened — no key yet, or the
   * request failed — and not as a gate. Nothing here disables the composer
   * while it runs: a control you cannot use until you have used another control
   * is the shape that made the microphone unusable, and the worst case here is
   * a first turn that takes the time it always used to.
   */
  useEffect(() => {
    if (!apiKey) return;
    void warm();
  }, [apiKey, warm]);

  const reset = useCallback(async () => {
    abortRef.current?.abort();
    await resetSession(sessionId).catch(() => undefined);
    // The receipt goes with the conversation it belongs to. Keeping it would
    // resume the trip that was just thrown away, on the next message.
    resumeRef.current = undefined;
    // A new conversation is cold again, so it warms again.
    warmedRef.current = false;
    setWarmth('cold');
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
   * Adds to the transcript as a spoken turn goes on.
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

  const liveStatusRef = useRef(liveStatus);
  liveStatusRef.current = liveStatus;

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

  const [session, setSession] = useState<VoiceSession | null>(null);
  /** The same session, readable synchronously — `setSession` lands a tick late. */
  const sessionRef = useRef<VoiceSession | null>(null);
  const [listening, setListening] = useState(false);
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);

  const closeVoice = useCallback(() => {
    session?.close();
    sessionRef.current = null;
    setSession(null);
    setListening(false);
    setAgentSpeaking(false);
  }, [session]);

  /**
   * Tap to talk. Tap again when you have finished talking.
   *
   * That is the whole interaction, and it is the one people already have with
   * the assistant on their phone. What was here instead was a *call*: the first
   * press dialled, the second hung up, and — because hanging up tears the
   * session down — speaking and then pressing stop threw away the answer on its
   * way back. Nobody dials an assistant.
   *
   * The setup is folded in rather than asked for. The Live API keeps no agent
   * object, so the first turn needs a handshake that binds the catalog, the
   * skill and the tools; that used to be a banner and a disabled microphone
   * until you pressed something. A microphone you cannot press is not a
   * microphone. Now the tap does it, and the button shows it is busy.
   */
  const toggleVoice = useCallback(async () => {
    // A session whose socket has gone is not a session. It answers every method
    // without complaint — `listen()` sets a flag and lights the microphone up —
    // and sends nothing, because `audioprocess` checks the socket and gives up.
    // Holding one turned the microphone into a button that visibly did
    // something and audibly did not. Drop it and open a fresh one below.
    if (session && !session.alive()) {
      sessionRef.current = null;
      setSession(null);
      setListening(false);
    } else if (session) {
      if (session.listening()) {
        session.stopListening();
        setListening(false);
      } else {
        session.listen();
        setListening(true);
      }
      return;
    }
    if (!keyRef.current) {
      setVoiceError('Add your Gemini key first.');
      return;
    }
    setVoiceError(null);

    // Bind the agent if this is the first thing said, or if the deployment has
    // moved on since it was bound.
    if (liveStatusRef.current !== 'ready' && !(await runInstantiate())) return;

    try {
      const started = await openVoice({
        origin: backendRef.current,
        sessionId,
        apiKey: keyRef.current,
        onSpeakingChange: setAgentSpeaking,
        // The relay ends when either side does, so an upstream session that
        // reaches its own limit takes this socket with it — without anybody
        // pressing anything. Let go of it here rather than waiting for the next
        // tap to notice.
        onClosed: () => {
          sessionRef.current = null;
          setSession(null);
          setListening(false);
        },
        onEvent: (event) => {
          switch (event.type) {
            case 'ui':
              store.apply(event.messages as never);
              // Spoken surfaces join the transcript like any other, so the
              // record of a spoken turn reads the same as a typed one.
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
      sessionRef.current = started;
      setSession(started);
      started.listen();
      setListening(true);
      return started;
    } catch (error) {
      setVoiceError(error instanceof Error ? error.message : String(error));
    }
  }, [session, runInstantiate, sessionId, store]);

  /**
   * Types into the Live session, opening it first if nothing is open.
   *
   * `toggleVoice` toggles, so this only reaches for it when there is
   * demonstrably no session — otherwise a typed line would close the
   * microphone on somebody mid-sentence.
   */
  const speak = useCallback(
    async (text: string): Promise<boolean> => {
      const existing = sessionRef.current ?? (await toggleVoice()) ?? null;
      if (!existing) return false;
      existing.say(text);
      return true;
    },
    [toggleVoice],
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
      toggle: toggleVoice,
      close: closeVoice,
      say: (text: string) => session?.say(text),
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
    /** Whether the agent has a conversation open and ready. See `warm`. */
    warmth,
    /** Starts one. Safe to call repeatedly; only the first does anything. */
    warm,
    drawSurface,
    stop,
    reset,
    handleSurfaceEvent,
  };
}

export type Agent = ReturnType<typeof useAgent>;
