/**
 * The session: a Durable Object holding one traveler's conversation.
 *
 * This is what makes the backend a *managed agent* rather than a stateless
 * endpoint. A Durable Object is a single-threaded actor with its own storage,
 * addressed by name — so one trip is one object, its turns are serialized
 * without any locking on our side, and its state outlives the request that
 * created it. That is the whole reason the browser can send "book the second
 * one" and have it mean something.
 *
 * What lives here:
 *   - the message history the model needs to continue a conversation, and
 *   - the trip state, which is the *durable* part: what the traveler has
 *     actually decided. History can be trimmed; decisions cannot.
 *
 * What deliberately does not live here: the API key. It arrives with each
 * request and leaves with it.
 */

import type Anthropic from '@anthropic-ai/sdk';

export interface SessionState {
  history: Anthropic.MessageParam[];
  trip: Record<string, unknown>;
  createdAt: number;
  updatedAt: number;
  turns: number;
}

/**
 * Turns kept in full before the history is trimmed.
 *
 * Trimming drops the oldest *pairs*, never a lone assistant message, because a
 * `tool_use` block with no matching `tool_result` after it is a 400 from the
 * API. The trip state is what carries continuity across a trim, which is why
 * the model is told to save decisions as it goes.
 */
const MAX_STORED_MESSAGES = 40;

const EMPTY: SessionState = { history: [], trip: {}, createdAt: 0, updatedAt: 0, turns: 0 };

/**
 * How long an untouched conversation is kept.
 *
 * Reloading the page starts a new conversation, which is what a person means by
 * reloading — and it means every reload leaves a Durable Object behind that
 * nothing will ever ask for again. Each one holds a transcript. So every write
 * pushes an alarm out to here, and the alarm deletes the session; a live
 * conversation keeps rearming it, an abandoned one expires.
 */
const SESSION_TTL_MS = 24 * 60 * 60 * 1000;

export class TripSession {
  constructor(private readonly state: DurableObjectState) {}

  /** Deletes an abandoned conversation. Rearmed by every write. */
  async alarm(): Promise<void> {
    await this.state.storage.deleteAll();
  }

  private async load(): Promise<SessionState> {
    const stored = await this.state.storage.get<SessionState>('state');
    if (stored) return stored;
    const now = Date.now();
    return { ...EMPTY, createdAt: now, updatedAt: now };
  }

  private async save(next: SessionState): Promise<void> {
    await this.state.storage.put('state', { ...next, updatedAt: Date.now() });
    await this.state.storage.setAlarm(Date.now() + SESSION_TTL_MS);
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname.endsWith('/get')) {
      return Response.json(await this.load());
    }

    if (url.pathname.endsWith('/put')) {
      const body = (await request.json()) as Partial<SessionState>;
      const current = await this.load();
      const history = trimHistory(body.history ?? current.history);
      await this.save({
        ...current,
        history,
        trip: body.trip ?? current.trip,
        turns: current.turns + 1,
      });
      return Response.json({ ok: true, turns: current.turns + 1, messages: history.length });
    }

    if (url.pathname.endsWith('/trip')) {
      const patch = (await request.json()) as Record<string, unknown>;
      const current = await this.load();
      await this.save({ ...current, trip: { ...current.trip, ...patch } });
      return Response.json({ ok: true });
    }

    if (url.pathname.endsWith('/reset')) {
      // deleteAll clears the alarm too, which is what we want: there is nothing
      // left to expire.
      await this.state.storage.deleteAll();
      return Response.json({ ok: true });
    }

    return new Response('Not found', { status: 404 });
  }
}

/**
 * Drops the oldest messages while keeping the transcript valid.
 *
 * Two invariants the API enforces: the first message must be from the user, and
 * every `tool_use` must be followed by its `tool_result`. So we cut from the
 * front until the next kept message is a plain user turn.
 */
export function trimHistory(history: Anthropic.MessageParam[]): Anthropic.MessageParam[] {
  if (history.length <= MAX_STORED_MESSAGES) return history;

  let start = history.length - MAX_STORED_MESSAGES;
  while (start < history.length) {
    const message = history[start]!;
    const isPlainUser =
      message.role === 'user' &&
      (typeof message.content === 'string' ||
        !message.content.some((block) => block.type === 'tool_result'));
    if (isPlainUser) break;
    start += 1;
  }
  return start >= history.length ? [] : history.slice(start);
}

/** Client for the Durable Object, so callers never build these URLs by hand. */
export class SessionClient {
  private readonly stub: DurableObjectStub;

  constructor(namespace: DurableObjectNamespace, sessionId: string) {
    this.stub = namespace.get(namespace.idFromName(sessionId));
  }

  async get(): Promise<SessionState> {
    const response = await this.stub.fetch('https://session/get');
    return (await response.json()) as SessionState;
  }

  async put(history: Anthropic.MessageParam[], trip: Record<string, unknown>): Promise<void> {
    await this.stub.fetch('https://session/put', {
      method: 'POST',
      body: JSON.stringify({ history, trip }),
    });
  }

  async patchTrip(patch: Record<string, unknown>): Promise<void> {
    await this.stub.fetch('https://session/trip', {
      method: 'POST',
      body: JSON.stringify(patch),
    });
  }

  async reset(): Promise<void> {
    await this.stub.fetch('https://session/reset', { method: 'POST' });
  }
}
