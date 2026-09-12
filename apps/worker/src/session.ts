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
 *   - the id of the last interaction, which is how the conversation continues,
 *     and
 *   - the trip state, which is the *durable* part: what the traveler has
 *     actually decided.
 *
 * The history itself is deliberately **not** here any more. The Interactions
 * API keeps the transcript server-side and `previous_interaction_id` chains to
 * it, so a tenth turn sends one message rather than re-uploading nine turns of
 * prose and tool results to ask one more question. That removed the trimming
 * problem along with the storage: there is no history to trim, and no way to
 * trim it into a `tool_use` with no matching result.
 *
 * The trip stays ours regardless. It is what the traveler decided, and it has to
 * survive a model that forgets, a chain that breaks, and a switch of runtime.
 *
 * What deliberately does not live here: the API key. It arrives with each
 * request and leaves with it.
 */

export interface SessionState {
  /** The last interaction in this conversation, or null before the first turn. */
  interactionId: string | null;
  trip: Record<string, unknown>;
  createdAt: number;
  updatedAt: number;
  turns: number;
  /**
   * The trip's decision shape when the standing surfaces were last drawn.
   *
   * Kept here rather than in the browser because the *server* decides when a
   * panel is owed a redraw now — a client that does not know what a trip is
   * cannot be the thing watching for one.
   */
  shape?: string;
}

const EMPTY: SessionState = {
  interactionId: null,
  trip: {},
  createdAt: 0,
  updatedAt: 0,
  turns: 0,
};

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
      await this.save({
        ...current,
        // `undefined` means "unchanged"; `null` is a real value here, and means
        // the chain was broken and the next turn starts a fresh one.
        interactionId:
          body.interactionId === undefined ? current.interactionId : body.interactionId,
        trip: body.trip ?? current.trip,
        shape: body.shape ?? current.shape,
        turns: current.turns + 1,
      });
      return Response.json({ ok: true, turns: current.turns + 1 });
    }

    if (url.pathname.endsWith('/trip')) {
      const patch = (await request.json()) as Record<string, unknown>;
      const current = await this.load();
      await this.save({ ...current, trip: { ...current.trip, ...patch } });
      return Response.json({ ok: true });
    }

    // A voice call is a WebSocket the DO holds open for as long as it lasts,
    // which is the whole reason it lives here: the trip it changes is the trip
    // the typed conversation is reading, in the same object, with no second
    // store to keep in step.
    if (url.pathname.endsWith('/voice')) {
      if (request.headers.get('Upgrade') !== 'websocket') {
        return new Response('Expected a WebSocket upgrade.', { status: 426 });
      }

      const pair = new WebSocketPair();
      const [browser, server] = Object.values(pair) as [WebSocket, WebSocket];
      server.accept();

      const state = await this.load();
      const { relay } = await import('./voice.js');
      const { buildSystemPrompt } = await import('./skills.js');
      const { CATALOG_ID } = await import('./agent.js');
      const { contractStamp } = await import('./contract.js');

      await relay({
        client: server,
        trip: state.trip,
        contract: contractStamp(),
        systemInstruction: buildSystemPrompt({
          variant: 'express-monolithic',
          surface: 'inline',
          surfaceId: 'voice',
          catalogId: CATALOG_ID,
          trip: state.trip,
          today: new Date().toISOString().slice(0, 10),
        }),
        onTrip: (trip) => {
          void this.save({ ...state, trip });
        },
      });

      return new Response(null, { status: 101, webSocket: browser });
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

  async put(
    interactionId: string | null,
    trip: Record<string, unknown>,
    shape?: string,
  ): Promise<void> {
    await this.stub.fetch('https://session/put', {
      method: 'POST',
      body: JSON.stringify({ interactionId, trip, ...(shape ? { shape } : {}) }),
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
