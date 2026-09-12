/**
 * Voice, over the Gemini Live API.
 *
 * The reason this exists is not that talking to a travel agent is novel. It is
 * that generative UI and speech fix each other's worst problem. Speech is an
 * excellent way to *ask* for four flights and a terrible way to *hear* them —
 * four fares read aloud is a memory test — while a screen is an excellent way to
 * show four fares and a clumsy way to describe a trip. So: the voice takes the
 * question, and the surface is the answer.
 *
 * That shape decides the whole design. The model is not asked to narrate a
 * flight list; it is given the same six surface tools the MCP endpoint exposes,
 * and told to draw. `show_flight_options` returns a one-line summary for it to
 * say and an A2UI surface for the browser to render, and those two things travel
 * down the same socket.
 *
 * **The relay is server-side, and that is the point.** The browser could open
 * this socket itself — the Live API is designed for it — and then the browser
 * would need the catalog, the compiler, the travel tools and the trip. Every
 * client would. Here the browser sends microphone bytes and receives audio plus
 * A2UI: exactly what a Swift or Kotlin client would send and receive, with
 * nothing travel-specific in it.
 *
 * Two details worth knowing before reading the code:
 *
 * **Audio is raw PCM in both directions, at different rates.** In: signed
 * 16-bit little-endian mono at 16 kHz. Out: the same at 24 kHz. Neither is
 * negotiable and getting one wrong produces confident nonsense rather than an
 * error.
 *
 * **A tool call pauses the turn.** Gemini sends `toolCall`, waits for
 * `toolResponse`, and only then finishes speaking — so a slow tool is dead air.
 * Everything these tools do is an in-Worker lookup, which is the reason that is
 * acceptable here and would not be against a real booking API.
 */

import type { A2uiMessage } from '@travel-a2ui/express';

import { CATALOG_ID } from './agent.js';
import { buildSurface, surfaceCompiler, MCP_TOOLS } from './mcp.js';
import { geminiTools, runTool, type ToolContext } from './tools.js';

/**
 * `https:`, not `wss:`.
 *
 * The Workers runtime opens an outbound WebSocket through `fetch` with an
 * `Upgrade` header, and `fetch` refuses a `wss:` URL outright — "Fetch API
 * cannot load", with the scheme as the only clue. The connection is the same
 * one; only the spelling differs.
 */
/** Flip while working on the relay to echo every Live frame into the log. */
const DEBUG = false;

const LIVE_ENDPOINT =
  'https://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent';

/** Native-audio models. Only these speak; the text models refuse `setup`. */
export const VOICE_MODEL = 'gemini-2.5-flash-native-audio-preview-09-2025';

/** What the browser sends up. */
export type ClientMessage =
  | { type: 'start'; apiKey: string; model?: string; voice?: string; trip?: Record<string, unknown> }
  /** Base64 PCM16 @ 16 kHz. */
  | { type: 'audio'; data: string }
  | { type: 'text'; text: string }
  | { type: 'end' };

/** What the browser gets back. Deliberately the same `ui` event the SSE turn emits. */
export type ServerMessage =
  | { type: 'ready'; model: string }
  | { type: 'audio'; data: string }
  | { type: 'transcript'; text: string; who: 'you' | 'agent' }
  | { type: 'ui'; surfaceId: string; messages: A2uiMessage[]; done: boolean }
  | { type: 'tool'; name: string; input: unknown }
  | { type: 'trip'; trip: Record<string, unknown> }
  | { type: 'turn_end' }
  | { type: 'error'; message: string };

/**
 * How to behave with a voice rather than a keyboard.
 *
 * Short, because it is appended to the same role the typed agent gets and the
 * differences really are only these. The big one is the last: reading a list out
 * loud is the failure mode this whole mode exists to avoid.
 */
const VOICE_BRIEF = `
You are on a phone call, not in a chat window. The traveler hears you and sees a
screen beside you.

- **Say one or two sentences, then draw.** Never read options aloud. Call a
  show_* tool and say what it is — "four fares up, the Iberia one is cheapest and
  gets in before lunch" — rather than reciting airlines and times.
- **Ask one thing at a time.** On a screen you can ask for dates, airport and
  party size at once. Out loud that is three questions in a row and nobody
  remembers the first.
- **Be brief.** Two sentences is usually one too many. No preamble, no
  "certainly", no repeating what they just said back to them.
- **Numbers out loud are rounded.** "About four hundred and twenty" — the screen
  has the exact figure.
- Never say the words A2UI, surface, component or tool.
`.trim();

/** The Live API's function-declaration shape, from either tool set. */
interface FunctionDeclaration {
  name: string;
  description: string;
  parameters?: Record<string, unknown>;
}

/**
 * Everything the model may call on a voice turn.
 *
 * The surface tools come first because they are what it should mostly be doing;
 * the data tools are there so it can save a decision or check the trip without
 * drawing anything.
 */
export function voiceTools(): FunctionDeclaration[] {
  const surfaces = MCP_TOOLS.filter((tool) => tool.name.startsWith('show_')).map((tool) => ({
    name: tool.name,
    description: tool.description,
    parameters: tool.inputSchema as Record<string, unknown>,
  }));

  const data = geminiTools()
    // `get_destination` and the pricing tools are useful; the surface tools
    // already price, so the overlap is intentional and cheap.
    .map((tool) => ({
      name: tool.name,
      description: tool.description,
      parameters: tool.parameters,
    }));

  return [...surfaces, ...data];
}

/** Strips JSON Schema keywords the Live API's function declarations reject. */
function liveSchema(schema: unknown): unknown {
  if (Array.isArray(schema)) return schema.map(liveSchema);
  if (!schema || typeof schema !== 'object') return schema;

  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(schema as Record<string, unknown>)) {
    // `additionalProperties`, `$schema` and `strict` are not part of the subset
    // the Live API accepts, and it rejects the whole setup rather than the key.
    if (key === 'additionalProperties' || key === '$schema' || key === 'strict') continue;
    out[key] = liveSchema(value);
  }
  return out;
}

/** The `setup` frame that opens a session. */
export function setupFrame(options: {
  model: string;
  systemInstruction: string;
  voice?: string;
}): unknown {
  return {
    setup: {
      model: `models/${options.model}`,
      generationConfig: {
        responseModalities: ['AUDIO'],
        ...(options.voice
          ? { speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: options.voice } } } }
          : {}),
      },
      systemInstruction: {
        parts: [{ text: `${options.systemInstruction}\n\n---\n\n${VOICE_BRIEF}` }],
      },
      tools: [
        {
          functionDeclarations: voiceTools().map((tool) => ({
            name: tool.name,
            description: tool.description,
            parameters: liveSchema(tool.parameters),
          })),
        },
      ],
      // Both transcripts, so the conversation has a readable record: what they
      // said is the only way to show a caller they were heard correctly.
      inputAudioTranscription: {},
      outputAudioTranscription: {},
    },
  };
}

export { VOICE_BRIEF };

/**
 * Runs one function call and says what to do with the result.
 *
 * A surface tool produces two things — a summary for the model to say and A2UI
 * for the browser to draw — and the split matters: sending the whole surface
 * back to the model would put a flight list in its context and invite it to read
 * the list out, which is the one thing this mode is for not doing.
 */
export async function runVoiceTool(
  name: string,
  args: Record<string, unknown>,
  context: ToolContext,
): Promise<{ response: unknown; ui?: { surfaceId: string; messages: A2uiMessage[] } }> {
  if (name.startsWith('show_') || name === 'render_a2ui_express') {
    try {
      // The tools take the trip as arguments; the session holds it, so it is
      // merged under whatever the model chose to pass.
      const surface = buildSurface(name, { ...context.trip, ...args });
      const messages = surfaceCompiler.compile(surface.express, {
        surfaceId: surface.surfaceId,
        catalogId: CATALOG_ID,
        version: 'v0.9.1',
      });
      return {
        response: { shown: true, summary: surface.summary },
        ui: { surfaceId: surface.surfaceId, messages },
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return { response: { shown: false, error: message } };
    }
  }

  const { result, isError } = await runTool(name, args, context);
  return { response: isError ? { error: result } : result };
}

/**
 * One voice call: the browser's socket on one side, Gemini Live on the other.
 *
 * Runs inside the session Durable Object, so the trip a call changes is the same
 * trip the typed conversation sees — say "make it three of us" out loud and the
 * panel moves, with no reload and no second store.
 */
export async function relay(options: {
  client: WebSocket;
  systemInstruction: string;
  trip: Record<string, unknown>;
  onTrip: (trip: Record<string, unknown>) => void;
}): Promise<void> {
  const { client } = options;
  const send = (message: ServerMessage) => {
    try {
      client.send(JSON.stringify(message));
    } catch {
      /* the browser went away mid-turn; the sockets close below */
    }
  };

  let upstream: WebSocket | null = null;
  const trip = { ...options.trip };
  const context: ToolContext = {
    trip,
    saveTrip: (patch) => {
      Object.assign(trip, patch);
      options.onTrip(trip);
      send({ type: 'trip', trip: { ...trip } });
    },
  };

  client.addEventListener('message', async (event) => {
    let message: ClientMessage;
    try {
      message = JSON.parse(String(event.data)) as ClientMessage;
    } catch {
      return;
    }

    if (message.type === 'start') {
      if (upstream) return;
      const model = message.model || VOICE_MODEL;
      try {
        // The key goes in the query string because a browser cannot set headers
        // on a WebSocket — but this half of the socket is server-to-server, so
        // the traveler's key never appears in a URL their browser requested.
        const response = await fetch(`${LIVE_ENDPOINT}?key=${encodeURIComponent(message.apiKey)}`, {
          headers: { Upgrade: 'websocket' },
        });
        upstream = response.webSocket;
        if (!upstream) {
          send({ type: 'error', message: `The Live API refused the connection (${response.status}).` });
          return;
        }
        upstream.accept();
        upstream.addEventListener('error', (e) =>
          send({ type: 'error', message: `Live socket error: ${String((e as ErrorEvent).message ?? e)}` }),
        );
        wire(upstream, send, context, () => trip);
        upstream.send(
          JSON.stringify(
            setupFrame({
              model,
              systemInstruction: options.systemInstruction,
              ...(message.voice ? { voice: message.voice } : {}),
            }),
          ),
        );
        send({ type: 'ready', model });
      } catch (error) {
        send({ type: 'error', message: describe(error) });
      }
      return;
    }

    if (!upstream) return;

    if (message.type === 'audio') {
      upstream.send(
        JSON.stringify({
          realtimeInput: {
            mediaChunks: [{ mimeType: 'audio/pcm;rate=16000', data: message.data }],
          },
        }),
      );
      return;
    }

    if (message.type === 'text') {
      upstream.send(
        JSON.stringify({
          clientContent: {
            turns: [{ role: 'user', parts: [{ text: message.text }] }],
            turnComplete: true,
          },
        }),
      );
      return;
    }

    if (message.type === 'end') {
      try {
        upstream.close();
      } catch {
        /* already gone */
      }
    }
  });

  client.addEventListener('close', () => {
    try {
      upstream?.close();
    } catch {
      /* already gone */
    }
  });
}

/** Translates Gemini's frames into ours, and answers its tool calls. */
function wire(
  upstream: WebSocket,
  send: (message: ServerMessage) => void,
  context: ToolContext,
  trip: () => Record<string, unknown>,
): void {
  upstream.addEventListener('message', async (event) => {
    // Three shapes, and the third is the one that cost an evening: the Workers
    // runtime hands an inbound frame over as a **Blob**, not a string and not
    // an ArrayBuffer. `TextDecoder().decode(blob)` does not throw — it produces
    // rubbish, `JSON.parse` fails, and the frame is dropped without a word. The
    // socket looked connected and simply never said anything.
    const raw = await readFrame(event.data);

    let frame: Record<string, any>;
    try {
      frame = JSON.parse(raw);
    } catch {
      return;
    }

    if (DEBUG) console.log('[live]', raw.slice(0, 400));
    if (frame['setupComplete']) return;

    const server = frame['serverContent'];
    if (server) {
      for (const part of server.modelTurn?.parts ?? []) {
        // Audio arrives as base64 PCM, already at 24 kHz. Straight through:
        // decoding it here would only be to re-encode it.
        if (part.inlineData?.data) send({ type: 'audio', data: part.inlineData.data });
      }
      if (server.outputTranscription?.text) {
        send({ type: 'transcript', text: server.outputTranscription.text, who: 'agent' });
      }
      if (server.inputTranscription?.text) {
        send({ type: 'transcript', text: server.inputTranscription.text, who: 'you' });
      }
      if (server.turnComplete) send({ type: 'turn_end' });
    }

    const call = frame['toolCall'];
    if (call?.functionCalls?.length) {
      const responses: unknown[] = [];
      for (const fn of call.functionCalls) {
        const args = (fn.args ?? {}) as Record<string, unknown>;
        send({ type: 'tool', name: fn.name, input: args });

        const outcome = await runVoiceTool(fn.name, { ...trip(), ...args }, context);
        if (outcome.ui) {
          send({ type: 'ui', surfaceId: outcome.ui.surfaceId, messages: outcome.ui.messages, done: true });
        }
        responses.push({ id: fn.id, name: fn.name, response: outcome.response });
      }
      // The turn is paused until this lands, so it goes back in one frame
      // rather than one per call.
      upstream.send(JSON.stringify({ toolResponse: { functionResponses: responses } }));
    }

    if (frame['goAway']) {
      send({ type: 'error', message: 'The Live session is closing — start another when ready.' });
    }
  });

  upstream.addEventListener('close', (event) => {
    const detail = (event as CloseEvent).reason;
    if (detail) send({ type: 'error', message: detail });
    send({ type: 'turn_end' });
  });
}

/** One inbound frame as text, whichever of the three shapes it arrived in. */
async function readFrame(data: unknown): Promise<string> {
  if (typeof data === 'string') return data;
  if (data instanceof ArrayBuffer) return new TextDecoder().decode(data);
  if (data && typeof (data as Blob).text === 'function') return (data as Blob).text();
  return '';
}

const describe = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);
