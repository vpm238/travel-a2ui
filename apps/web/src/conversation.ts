/**
 * What a turn is, and how one grows while the agent is answering.
 *
 * A turn is not "some text, then a surface". A model says a sentence, draws,
 * and says another sentence, so a turn is a *sequence* of parts and these are
 * the two functions that extend it: one for prose as it streams, one for a
 * surface the moment it is first seen.
 *
 * Nothing here is React, and nothing here knows what a trip is. That is on
 * purpose — see `Trip`.
 */

import type { SurfacePress } from './surfaces.js';

import type { SkillVariant, SurfaceAction } from './api.js';

/**
 * The trip, as far as this client is concerned: whatever the server sent.
 *
 * Deliberately opaque: this is a renderer, and it does not know what a trip
 * is. Every client gets the same panel because the server, not the client,
 * keeps it current.
 */
export type Trip = Record<string, unknown>;

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
  { kind: 'text'; text: string; round: number } | { kind: 'surface'; surfaceId: string };

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
  /** True for a turn of the recorded sample trip, which nobody in this session said. */
  sample?: boolean;
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
export function withText(parts: TurnPart[], delta: string, round: number): TurnPart[] {
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
export const STANDING = new Set(['sidebar', 'home']);

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
export function withSurface(parts: TurnPart[], surfaceId: string): TurnPart[] {
  if (STANDING.has(surfaceId)) return parts;
  if (parts.some((part) => part.kind === 'surface' && part.surfaceId === surfaceId)) return parts;
  return [...parts, { kind: 'surface', surfaceId }];
}

/** Whether any turn already shows this surface. */
export function isShown(turns: Turn[], surfaceId: string): boolean {
  return turns.some((turn) =>
    turn.parts.some((part) => part.kind === 'surface' && part.surfaceId === surfaceId),
  );
}

/**
 * Files a surface under the turn that first shows it, and nowhere else.
 *
 * A later turn can send data to an earlier card (a press selects a flight,
 * and the card marks it). That event updates the card where it already is; it
 * does not draw the card a second time under the later turn.
 */
export function placeSurface(turns: Turn[], turnId: string, surfaceId: string): Turn[] {
  if (isShown(turns, surfaceId)) return turns;
  return turns.map((turn) =>
    turn.id === turnId ? { ...turn, parts: withSurface(turn.parts, surfaceId) } : turn,
  );
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
 * No model or effort: the server chooses one for the conversation and the
 * panel alike, so sending nothing is the honest default.
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

export const EMPTY_USAGE: Usage = {
  inputTokens: 0,
  outputTokens: 0,
  cacheReadTokens: 0,
  cacheWriteTokens: 0,
  thoughtTokens: 0,
  turns: 0,
};

/**
 * An interaction, in the shape A2UI already defines for one.
 *
 * Not a prose sentence: a synthetic prose format would be an application
 * protocol on top of A2UI that no other renderer knows. Every A2UI renderer
 * already resolves an action's bound context and hands it over, which is this.
 *
 * `context` is the answer the traveller is sending. The surfaces' data models
 * travel separately, as `a2uiRendererDataModel` metadata on every request
 * (`docs/transport.md`); the copy here is only for the transcript's label.
 */
/**
 * Finds a component on a surface. The renderer's store answers it today; the
 * function is the seam, so the transcript does not care which model holds the
 * tree.
 */
export type ComponentLookup = (surfaceId: string, id: string) => Record<string, unknown> | undefined;

/**
 * How an interaction reads in the transcript.
 *
 * Display only — and, during a call, what is said to the Live session, which
 * has no equivalent of an A2UI action. The wire carries the action; this is so
 * the conversation has a line where the traveler's turn was.
 *
 * Not the action's context verbatim, which would put the protocol in the
 * traveller's own speech bubble. It says what was pressed, in the words the surface already put on it, then the
 * values it carried, written for a person:
 *
 *     Send — origin: JFK, start date: 12 Apr 2027
 *
 * Nothing here knows what a trip is. The label is the pressed component's own
 * — its `accessibility.label`, or the text on its face — and the values are
 * formatted by shape, not by name: a calendar date reads as a date, a JSON
 * pointer is plumbing and is dropped, a key is split into words.
 */
export function describeForTranscript(action: SurfaceAction, lookup?: ComponentLookup): string {
  // The action's own sentence, when the surface wrote one: A2UI's `userMessage`
  // is exactly "a user-facing message explaining the action".
  if (action.userMessage?.trim()) return action.userMessage.trim();
  const label = lookup ? pressedLabel(action, lookup) : undefined;
  const said = Object.entries(action.context)
    .map(([key, value]) => [key, readable(value)] as const)
    .filter((entry): entry is readonly [string, string] => entry[1] !== undefined)
    // A value the label already says is not worth saying twice — a fare card
    // named "Iberia IB6250, …" does not need "flight: IB6250" after it.
    .filter(([, value]) => !label || !says(label, value))
    .map(([key, value]) => `${words(key)}: ${value}`)
    .join(', ');
  const head = label ?? sentenceCase(words(action.name));
  return said ? `${head} — ${said}` : head;
}

/**
 * The name the surface gave whatever was pressed.
 *
 * `accessibility.label` first, because it is the name an author wrote for
 * exactly this — what the control is called when it cannot be seen. Then the
 * text on its face: a Button's `child`, or the first Text under it.
 */
export function pressedLabel(action: SurfaceAction, lookup: ComponentLookup): string | undefined {
  const id = action.sourceComponentId;
  if (!id) return undefined;
  const node = lookup(action.surfaceId, id);
  if (!node) return undefined;

  const accessibility = node['accessibility'];
  if (accessibility && typeof accessibility === 'object') {
    const named = textOf((accessibility as Record<string, unknown>)['label'], action.dataModel ?? {});
    if (named) return named;
  }
  return faceOf(node, action, lookup, new Set([id]));
}

function faceOf(
  node: Record<string, unknown>,
  action: SurfaceAction,
  lookup: ComponentLookup,
  seen: Set<string>,
): string | undefined {
  if (node['component'] === 'Text') return textOf(node['text'], action.dataModel ?? {});
  const children: unknown[] = [];
  if (typeof node['child'] === 'string') children.push(node['child']);
  if (Array.isArray(node['children'])) children.push(...node['children']);
  for (const child of children) {
    if (typeof child !== 'string' || seen.has(child) || seen.size > 12) continue;
    seen.add(child);
    const next = lookup(action.surfaceId, child);
    const found = next ? faceOf(next, action, lookup, seen) : undefined;
    if (found) return found;
  }
  return undefined;
}

/** A literal string, or an absolute binding read from the data model sent with the action. */
function textOf(value: unknown, dataModel: Record<string, unknown>): string | undefined {
  if (typeof value === 'string') return value.trim() || undefined;
  if (!value || typeof value !== 'object') return undefined;
  const path = (value as Record<string, unknown>)['@path'] ?? (value as Record<string, unknown>)['path'];
  if (typeof path !== 'string' || !path.startsWith('/')) return undefined;
  let at: unknown = dataModel;
  for (const raw of path.split('/').slice(1)) {
    const key = raw.replace(/~1/g, '/').replace(/~0/g, '~');
    if (!at || typeof at !== 'object') return undefined;
    at = (at as Record<string, unknown>)[key];
  }
  return typeof at === 'string' || typeof at === 'number' ? String(at).trim() || undefined : undefined;
}

const POINTER = /^\/[^\s]+$/;
const CIVIL = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$/;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/**
 * A value as a person would say it, or `undefined` when there is nothing to say.
 *
 * By shape only. Dates are formatted from their digits rather than through
 * `Date`, which would move a day by the viewer's offset.
 */
export function readable(value: unknown): string | undefined {
  if (value === null || value === undefined || value === '') return undefined;
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : undefined;
  if (typeof value === 'string') {
    if (POINTER.test(value)) return undefined;
    const civil = CIVIL.exec(value);
    if (civil) {
      const [, year, month, day, hour, minute] = civil;
      const monthName = MONTHS[Number(month) - 1];
      if (monthName && Number(day) >= 1 && Number(day) <= 31) {
        const date = `${Number(day)} ${monthName} ${year}`;
        return hour && !(hour === '00' && minute === '00') ? `${date}, ${hour}:${minute}` : date;
      }
    }
    return value;
  }
  if (Array.isArray(value)) {
    const parts = value.map(readable).filter((part): part is string => part !== undefined);
    return parts.length ? parts.join(', ') : undefined;
  }
  return JSON.stringify(value);
}

/** Whether `text` already says `value`, as a whole word — "$412" does not say "2". */
function says(text: string, value: string): boolean {
  const escaped = value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`(^|[^\\p{L}\\p{N}])${escaped}($|[^\\p{L}\\p{N}])`, 'u').test(text);
}

/** `startDate` and `start_date` both say "start date". */
function words(key: string): string {
  return key
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .toLowerCase()
    .trim();
}

function sentenceCase(text: string): string {
  return text ? text[0]!.toUpperCase() + text.slice(1) : text;
}

/** A press from the SDK, as the app holds it; `dataModel` names it in the transcript. */
export function actionFrom(press: SurfacePress, dataModel: Record<string, unknown> = {}): SurfaceAction {
  return {
    name: press.name,
    surfaceId: press.surfaceId,
    sourceComponentId: press.sourceComponentId ?? '',
    ...(press.userMessage ? { userMessage: press.userMessage } : {}),
    timestamp: press.timestamp || new Date().toISOString(),
    context: press.context ?? {},
    dataModel,
  };
}
