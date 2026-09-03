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
import {
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
  const [trip, setTrip] = useState<Record<string, unknown>>({});
  const [usage, setUsage] = useState<Usage>(EMPTY_USAGE);
  const [busy, setBusy] = useState(false);
  const [liveSurface, setLiveSurface] = useState<SurfaceKind | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  // Read inside callbacks that must not be recreated on every keystroke.
  const prefsRef = useRef(prefs);
  prefsRef.current = prefs;
  const keyRef = useRef(apiKey);
  keyRef.current = apiKey;

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
            store.apply(event.messages);
            if (!options.silent) {
              patchTurn(assistantId, (turn) => ({
                parts: withSurface(turn.parts, event.surfaceId),
              }));
            }
            break;
          case 'ui_error':
            if (!options.silent) patchTurn(assistantId, { error: event.message });
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

  /** Wired to every surface: an interaction is the user's next turn. */
  const handleSurfaceEvent = useCallback(
    (event: A2uiEvent) => {
      if (busy) return;
      const surface: SurfaceKind =
        event.surfaceId === 'sidebar' ? 'sidebar' : event.surfaceId === 'home' ? 'home' : 'inline';
      void send(describeEvent(event), {
        surface,
        surfaceState: event.dataModel,
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
  };
}

export type Agent = ReturnType<typeof useAgent>;
