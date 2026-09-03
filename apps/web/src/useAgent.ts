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
import { TRIP_KEYS, plan as planTrip, type Trip } from '@travel-a2ui/trip';

import { consumeKeyFromUrl } from './apiKey.js';
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
  type SurfaceKind,
} from './api.js';

const API_KEY = 'travel-a2ui:key';
const PREFS_KEY = 'travel-a2ui:prefs';
const BACKEND_KEY = 'travel-a2ui:backend';

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

/** Records a surface once; later events for it only update the store. */
function withSurface(parts: TurnPart[], surfaceId: string): TurnPart[] {
  if (parts.some((part) => part.kind === 'surface' && part.surfaceId === surfaceId)) return parts;
  return [...parts, { kind: 'surface', surfaceId }];
}

export interface Usage {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
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
 * Trip facts that live at `/trip` in every surface's data model.
 *
 * The old arrangement was the root of "it forgot what I picked": each surface
 * had its own data model, born empty, while the trip was durable and lived
 * somewhere else entirely. So the second card had no idea what you answered on
 * the first unless the model happened to remember to write it back in.
 *
 * Now the host bridges the two. A surface is seeded from the trip as it arrives,
 * so a control bound to `$/trip/startDate` is pre-filled with the dates already
 * agreed, on every surface, without the model doing anything. And committing a
 * surface sends its `/trip` values back, where the Worker merges them into the
 * durable trip. What you set on screen is remembered because the host remembers
 * it, not because the model was asked nicely.
 */
/** Read once, at module load: it does not change while the tab is open. */
const HINTS = clientHints();

const TRIP_FIELDS = TRIP_KEYS;

/**
 * Fills a new surface's `/trip` with what is already known.
 *
 * Only fields the surface left undefined: a model that deliberately set a value
 * — a suggested date, a widened budget — is proposing something, and that
 * proposal should win over the older fact it is proposing to change.
 */
function seedTrip(store: SurfaceStore, surfaceId: string, trip: Record<string, unknown>): void {
  const current = (store.snapshot(surfaceId)['trip'] ?? {}) as Record<string, unknown>;
  for (const field of TRIP_FIELDS) {
    const value = trip[field];
    if (value === undefined || value === null || value === '') continue;
    if (current[field] !== undefined) continue;
    store.setValue(surfaceId, `/trip/${field}`, value as never);
  }
}

/**
 * Pushes the trip into a standing panel, overwriting what is there.
 *
 * The panels are meant to show where the trip *is*. Changing the departure
 * airport on an inline card and watching the sidebar carry on displaying the
 * old one is the panel lying about the trip — and rebuilding it through the
 * model to fix that costs a round trip and several seconds for values the host
 * already has.
 *
 * So: values sync here, immediately and for free. The model is only asked to
 * rebuild when the panel should be a *different shape*, which is a much rarer
 * event than a value changing.
 *
 * Only `sidebar` and `home` — a spent inline card is the record of what was
 * asked at the time, and rewriting history under it would be worse than stale.
 */
function syncTrip(store: SurfaceStore, surfaceId: string, trip: Record<string, unknown>): void {
  if (!store.get(surfaceId)) return;
  const current = (store.snapshot(surfaceId)['trip'] ?? {}) as Record<string, unknown>;
  for (const field of TRIP_FIELDS) {
    const value = trip[field];
    if (value === undefined || value === null || value === '') continue;
    if (current[field] === value) continue;
    store.setValue(surfaceId, `/trip/${field}`, value as never);
  }
}

/**
 * Components that edit a value rather than make a decision.
 *
 * The distinction runs the whole interaction model. Dragging a slider, picking
 * a date, ticking a box, typing a name — those are someone composing an answer,
 * and sending a turn on each one means the third choice arrives in a surface
 * that has forgotten the first two. Tapping a flight, or pressing a button, is
 * someone *finishing*. Only the second kind starts a turn.
 *
 * The renderer already declines to fire actions from these; this is the host
 * saying the same thing, so a component added later cannot quietly reintroduce
 * the behaviour.
 */
const VALUE_EDITORS = new Set([
  'TextField',
  'CheckBox',
  'ChoicePicker',
  'Slider',
  'DateTimeInput',
  'DateRangePicker',
  'TravelerCounter',
]);

/** Turns an interface event into the sentence the model receives. */
function describeEvent(event: A2uiEvent): string {
  const entries = Object.entries(event.context ?? {}).filter(
    ([, value]) => value !== null && value !== undefined && value !== '',
  );
  const detail = entries.length
    ? ` (${entries.map(([key, value]) => `${key}: ${JSON.stringify(value)}`).join(', ')})`
    : '';
  return `[interface] ${event.name}${detail}`;
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
    return { model: 'claude-opus-5', skill: 'express-monolithic', effort: 'medium' };
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
  // Read while a turn is streaming, where `trip` in the closure is stale.
  const tripRef = useRef(trip);
  tripRef.current = trip;

  /**
   * Keeps the standing panels showing the trip as it actually stands.
   *
   * Runs on every trip change, which is cheap — a handful of pointer writes —
   * and is why editing the route on an inline card is visible in the sidebar
   * before the next turn finishes rather than after a rebuild.
   */
  useEffect(() => {
    syncTrip(store, 'sidebar', trip);
    syncTrip(store, 'home', trip);
  }, [store, trip]);

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
   * Switches runtime, but only after the new one answers.
   *
   * Probing first means picking a backend that is not running tells you so
   * here, with the URL you gave it, instead of failing on the next message with
   * a network error that looks like the model's fault.
   */
  const setBackend = useCallback(async (id: BackendId, origin: string): Promise<boolean> => {
    const clean = origin.replace(/\/$/, '');
    setBackendError(null);
    try {
      const loaded = await probeBackend(clean || window.location.origin);
      setApiOrigin(clean);
      setBackendState({ id, origin: clean });
      writeStored(BACKEND_KEY, JSON.stringify({ id, origin: clean }));
      setMeta(loaded);
      setMetaError(null);
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

  const send = useCallback(
    async (
      message: string,
      options: {
        surface?: SurfaceKind;
        surfaceId?: string;
        surfaceState?: Record<string, unknown>;
        fromSurface?: boolean;
        /** Keep the transcript clean for background surfaces like the home screen. */
        silent?: boolean;
      } = {},
    ) => {
      const text = message.trim();
      if (!text || busy) return;

      const surface = options.surface ?? 'inline';
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
            store.apply(event.messages);
            // Seeded on every ui event, not just the first: a surface streams in
            // and its data model can arrive after the components that read it.
            seedTrip(store, event.surfaceId, tripRef.current);
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
          case 'usage':
            setUsage((current) => ({
              inputTokens: current.inputTokens + event.inputTokens,
              outputTokens: current.outputTokens + event.outputTokens,
              cacheReadTokens: current.cacheReadTokens + event.cacheReadTokens,
              cacheWriteTokens: current.cacheWriteTokens + event.cacheWriteTokens,
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
            message: text,
            surface,
            skill: prefsRef.current.skill,
            model: prefsRef.current.model,
            effort: prefsRef.current.effort,
            ...(options.surfaceId ? { surfaceId: options.surfaceId } : {}),
            ...(options.surfaceState ? { surfaceState: options.surfaceState } : {}),
            ...(HINTS ? { client: HINTS } : {}),
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
  const handleSurfaceEvent = useCallback(
    (event: A2uiEvent) => {
      if (busy) return;
      if (event.source && VALUE_EDITORS.has(event.source.component)) return;

      const surface: SurfaceKind =
        event.surfaceId === 'sidebar' ? 'sidebar' : event.surfaceId === 'home' ? 'home' : 'inline';

      // The panel is read-only, so an interaction there is not an answer — it
      // is a request to re-open a decision. Deciding happens in the
      // conversation, where there is a record of it, and one place to edit a
      // value rather than two that can disagree.
      if (surface !== 'inline') {
        const field = event.context['field'];
        void send(
          field
            ? `[interface] change ${String(field)} — release it and ask me again inline, ` +
              'pre-filled with what was there.'
            : // Anything else in the panel is the agent having asked a question
              // in the record rather than in the conversation. Answering it here
              // would put the question in the one place that cannot hold one, so
              // it is redirected instead of dropped.
              `[interface] I pressed "${event.name.replace(/_/g, ' ')}" in the panel. The panel is ` +
              'read-only — ask me that in the conversation instead, with the controls it needs.',
          { surface: 'inline', surfaceState: event.dataModel, fromSurface: true },
        );
        return;
      }

      void send(describeEvent(event), {
        surface,
        surfaceState: event.dataModel,
        fromSurface: true,
      });
    },
    [busy, send],
  );

  /**
   * Sends a surface's current values without a specific decision attached.
   *
   * The escape hatch for a card full of editors and no commit button: the model
   * is supposed to draw one, and when it does not, the traveler is otherwise
   * stuck holding an answer with no way to hand it over.
   */
  const submitSurface = useCallback(
    (surfaceId: string, label = 'submitted the panel') => {
      if (busy) return;
      const surface: SurfaceKind =
        surfaceId === 'sidebar' ? 'sidebar' : surfaceId === 'home' ? 'home' : 'inline';
      const values = store.snapshot(surfaceId);
      void send(`[interface] ${label} ${JSON.stringify(values)}`, {
        surface,
        surfaceState: values,
        fromSurface: true,
      });
    },
    [busy, send, store],
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

  return {
    store,
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
    stop,
    reset,
    handleSurfaceEvent,
    submitSurface,
  };
}

export type Agent = ReturnType<typeof useAgent>;
