/**
 * The Worker: API, MCP endpoint, and the built React app, on one origin.
 *
 * ## Where the API key lives
 *
 * Nowhere. The browser holds it, sends it on each request in `x-anthropic-key`,
 * and this Worker passes it straight to the Anthropic SDK and forgets it. It is
 * never written to a Durable Object, never logged, never put in a URL (where it
 * would land in request logs), and never stored in a Worker secret — because
 * this is a bring-your-own-key app and the key belongs to whoever is using it.
 *
 * That is a real trade, so state it plainly: it means anyone who opens the app
 * spends their own quota and nobody else's, and it means the key sits in that
 * browser's localStorage, which is exactly as safe as that browser. For a shared
 * deployment where you want one org key instead, set an `ANTHROPIC_API_KEY`
 * secret and it is used when the header is absent — see the README.
 */

import type Anthropic from '@anthropic-ai/sdk';

import { ExpressCompiler, ExpressDecompiler } from '@travel-a2ui/express';

import { CATALOG, CATALOG_ID, runTurn, type AgentEvent, type TurnRequest } from './agent.js';
import { handleMcp, MCP_TOOLS } from './mcp.js';
import { SessionClient, TripSession } from './session.js';
import { describeAllSkills, isSkillVariant, type SkillVariant, type SurfaceKind } from './skills.js';
import { knownDestinations } from './travel.js';

export { TripSession };

export interface Env {
  TRIP_SESSION: DurableObjectNamespace;
  ASSETS: Fetcher;
  DEFAULT_MODEL?: string;
  DEFAULT_SKILL?: string;
  PUBLIC_NAME?: string;
  /** Optional shared key for a deployment that does not want to ask for one. */
  ANTHROPIC_API_KEY?: string;
  /**
   * Where the Python managed-agent backend is, if one is running.
   *
   * The app offers both runtimes in a picker; this is only the default it
   * suggests, and the picker lets you type another. Leave it unset and the
   * option is still there, it just asks where to find it.
   */
  MANAGED_AGENT_ORIGIN?: string;
}

const MODELS = [
  { id: 'claude-opus-5', label: 'Opus 5', note: 'Best judgement and layout sense' },
  { id: 'claude-sonnet-5', label: 'Sonnet 5', note: 'Faster, noticeably cheaper' },
  { id: 'claude-haiku-4-5', label: 'Haiku 4.5', note: 'Fastest; simpler surfaces' },
] as const;

const SURFACES: SurfaceKind[] = ['inline', 'sidebar', 'home'];

const json = (body: unknown, status = 200) =>
  Response.json(body, { status, headers: { 'cache-control': 'no-store' } });

const problem = (message: string, status: number, hint?: string) =>
  json({ error: message, ...(hint ? { hint } : {}) }, status);

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === 'OPTIONS') {
      return new Response(null, {
        status: 204,
        headers: {
          'access-control-allow-origin': '*',
          'access-control-allow-methods': 'GET, POST, OPTIONS',
          'access-control-allow-headers': 'content-type, x-anthropic-key, mcp-protocol-version',
          'access-control-max-age': '86400',
        },
      });
    }

    // The MCP endpoint is CORS-open on purpose: it is meant to be called by
    // other agent hosts, and it holds no credentials of its own.
    if (path === '/mcp' || path.startsWith('/mcp/')) {
      // The MCP app's view template is composed from this deployment's own
      // assets, so the handler needs the binding.
      const response = await handleMcp(request, env.ASSETS);
      const headers = new Headers(response.headers);
      headers.set('access-control-allow-origin', '*');
      return new Response(response.body, { status: response.status, headers });
    }

    // The renderer the MCP shell loads. It is fetched by an iframe in someone
    // else's app — often with an opaque origin — so it has to be readable from
    // anywhere, and it is a static bundle with no key and no session in it.
    if (path.startsWith('/mcp-view/')) {
      const asset = await env.ASSETS.fetch(request);
      if (!asset.ok) return asset;
      const headers = new Headers(asset.headers);
      headers.set('access-control-allow-origin', '*');
      // Short, not immutable: the filename is stable across deploys, so a long
      // cache would pin an old renderer to a new payload.
      headers.set('cache-control', 'public, max-age=300, stale-while-revalidate=86400');
      return new Response(asset.body, { status: asset.status, headers });
    }

    if (path === '/.well-known/mcp.json') {
      return json({
        name: 'travel-a2ui',
        version: '0.1.0',
        transport: 'streamable-http',
        endpoint: new URL('/mcp', url.origin).toString(),
        tools: MCP_TOOLS.map((tool) => ({ name: tool.name, title: tool.title })),
      });
    }

    if (path === '/api/meta') return handleMeta(env);
    if (path === '/api/chat' && request.method === 'POST') return handleChat(request, env, ctx);
    if (path === '/api/session' && request.method === 'GET') return handleGetSession(url, env);
    if (path === '/api/session/reset' && request.method === 'POST') return handleReset(request, env);
    if (path === '/api/catalog') {
      return Response.json(CATALOG, { headers: { 'cache-control': 'public, max-age=300' } });
    }
    if (path === '/api/compile' && request.method === 'POST') return handleCompile(request);
    if (path === '/api/decompile' && request.method === 'POST') return handleDecompile(request);
    if (path.startsWith('/api/')) return problem(`No API route for ${path}`, 404);

    return env.ASSETS.fetch(request);
  },
};

/**
 * The compiler, as a service.
 *
 * Express in, A2UI out. It exists because the compiler is the one piece every
 * runtime needs and nobody should have to reimplement: a Python backend, a
 * mobile host, a notebook, anything that can POST can now speak Express without
 * shipping a parser.
 *
 * No key, no session, no state — this is a pure function over a request body,
 * and it is CORS-open for the same reason the MCP endpoint is.
 */
async function handleCompile(request: Request): Promise<Response> {
  let body: { source?: string; surfaceId?: string; catalogId?: string; isFinal?: boolean };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return problem('Body is not JSON', 400);
  }

  const source = body.source;
  if (typeof source !== 'string' || !source.trim()) {
    return problem('source is required', 400, 'Send { "source": "root = Text(\"Hi\")" }.');
  }
  if (source.length > 200_000) return problem('source is too long (200 kB max)', 413);

  try {
    const messages = new ExpressCompiler(CATALOG, 'v0.9.1').compile(source, {
      surfaceId: body.surfaceId ?? 'default_surface',
      catalogId: body.catalogId ?? CATALOG_ID,
      version: 'v0.9.1',
      ...(body.isFinal === false ? { isFinal: false } : {}),
    });
    return cors(json({ messages, catalogId: CATALOG_ID, version: 'v0.9.1' }));
  } catch (error) {
    // A compile failure is the caller's to fix, and the message names what was
    // wrong — so it is a 422 with detail, not a 500.
    return cors(
      json({ error: error instanceof Error ? error.message : String(error), source: 'compile' }, 422),
    );
  }
}

/** A2UI in, Express out — the same decompiler the Wire view uses. */
async function handleDecompile(request: Request): Promise<Response> {
  let body: { messages?: unknown; useKeywordArgs?: boolean };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return problem('Body is not JSON', 400);
  }

  const messages = body.messages;
  if (!messages || (Array.isArray(messages) && messages.length === 0)) {
    return problem('messages is required', 400, 'Send { "messages": [ …A2UI messages… ] }.');
  }

  try {
    const express = new ExpressDecompiler(CATALOG).decompile(messages as never, {
      ...(body.useKeywordArgs ? { useKeywordArgs: true } : {}),
    });
    return cors(json({ express }));
  } catch (error) {
    return cors(
      json({ error: error instanceof Error ? error.message : String(error), source: 'decompile' }, 422),
    );
  }
}

function cors(response: Response): Response {
  const headers = new Headers(response.headers);
  headers.set('access-control-allow-origin', '*');
  return new Response(response.body, { status: response.status, headers });
}

function handleMeta(env: Env): Response {
  return json({
    name: env.PUBLIC_NAME ?? 'Travel A2UI',
    catalogId: CATALOG_ID,
    protocolVersion: 'v0.9.1',
    defaultModel: env.DEFAULT_MODEL ?? 'claude-opus-5',
    defaultSkill: env.DEFAULT_SKILL ?? 'express-monolithic',
    models: MODELS,
    surfaces: SURFACES,
    skills: describeAllSkills(),
    destinations: knownDestinations().map((entry) => ({
      city: entry.city,
      country: entry.country,
      airport: entry.airport,
      summary: entry.summary,
    })),
    mcpEndpoint: '/mcp',
    /** True when the deployment carries its own key and the UI need not ask. */
    keyProvided: Boolean(env.ANTHROPIC_API_KEY),
    runtime: 'worker',
    /**
     * The two runtimes, offered to the front end as a choice.
     *
     * They answer the same wire protocol from the same catalog and the same
     * skills, which is what makes them interchangeable at all — the difference
     * is who runs the agent loop, not what comes out of it.
     */
    backends: [
      {
        id: 'worker',
        label: 'Cloudflare Worker',
        origin: '',
        note: 'The loop runs at the edge, in this Worker. One deploy, no second service, sessions in a Durable Object.',
      },
      {
        id: 'managed-agent',
        label: 'Claude Managed Agent',
        origin: env.MANAGED_AGENT_ORIGIN ?? '',
        note: 'Anthropic runs the loop and hosts the sandbox; the Python backend in backends/ provisions the agent and relays the same events.',
      },
    ],
  });
}

async function handleGetSession(url: URL, env: Env): Promise<Response> {
  const sessionId = url.searchParams.get('sessionId');
  if (!sessionId) return problem('sessionId is required', 400);
  const session = new SessionClient(env.TRIP_SESSION, sessionId);
  const state = await session.get();
  return json({ trip: state.trip, turns: state.turns, messages: state.history.length });
}

async function handleReset(request: Request, env: Env): Promise<Response> {
  const body = (await request.json().catch(() => ({}))) as { sessionId?: string };
  if (!body.sessionId) return problem('sessionId is required', 400);
  await new SessionClient(env.TRIP_SESSION, body.sessionId).reset();
  return json({ ok: true });
}

interface ChatBody {
  sessionId?: string;
  message?: string;
  surface?: string;
  surfaceId?: string;
  skill?: string;
  model?: string;
  effort?: string;
  surfaceState?: Record<string, unknown>;
  client?: { timeZone?: string; locale?: string };
}

async function handleChat(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const apiKey = request.headers.get('x-anthropic-key')?.trim() || env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return problem(
      'No Anthropic API key.',
      401,
      'Add your key in the app — it is kept in this browser and sent with each request.',
    );
  }

  let body: ChatBody;
  try {
    body = (await request.json()) as ChatBody;
  } catch {
    return problem('Body is not JSON', 400);
  }

  const message = (body.message ?? '').trim();
  if (!message) return problem('message is required', 400);
  if (message.length > 8000) return problem('message is too long (8000 characters max)', 413);

  const sessionId = body.sessionId?.trim();
  if (!sessionId) return problem('sessionId is required', 400);

  const surface: SurfaceKind = SURFACES.includes(body.surface as SurfaceKind)
    ? (body.surface as SurfaceKind)
    : 'inline';
  const skill: SkillVariant = isSkillVariant(body.skill)
    ? body.skill
    : ((env.DEFAULT_SKILL as SkillVariant) ?? 'express-monolithic');
  const model = MODELS.some((entry) => entry.id === body.model)
    ? body.model!
    : (env.DEFAULT_MODEL ?? 'claude-opus-5');
  const effort = (['low', 'medium', 'high'] as const).includes(body.effort as never)
    ? (body.effort as 'low' | 'medium' | 'high')
    : 'medium';

  const session = new SessionClient(env.TRIP_SESSION, sessionId);
  const state = await session.get();

  const surfaceId =
    body.surfaceId?.trim() ||
    (surface === 'inline' ? `inline-${state.turns + 1}` : surface);

  const turn: TurnRequest = {
    apiKey,
    model,
    message,
    history: state.history,
    trip: state.trip,
    surface,
    surfaceId,
    skill,
    effort,
    ...(body.surfaceState ? { surfaceState: body.surfaceState } : {}),
    ...(body.client ? { client: body.client } : {}),
  };

  return streamTurn(turn, session, ctx);
}

/**
 * Streams a turn to the browser as Server-Sent Events.
 *
 * SSE rather than a WebSocket because the traffic is one-way and bursty: the
 * client sends one message and reads until the turn ends. It reconnects for
 * free, survives proxies that mangle upgrades, and needs no protocol of its own.
 */
function streamTurn(turn: TurnRequest, session: SessionClient, ctx: ExecutionContext): Response {
  const encoder = new TextEncoder();
  let closed = false;

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const send = (event: AgentEvent) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
        } catch {
          closed = true;
        }
      };

      const work = (async () => {
        try {
          const result = await runTurn(turn, send);
          // Persist after the turn, not during: a turn that fails halfway
          // should not leave a transcript the model cannot continue from.
          await session.put(result.history, result.trip);
        } catch (error) {
          send({
            type: 'error',
            message: error instanceof Error ? error.message : String(error),
            retryable: true,
          });
        } finally {
          if (!closed) {
            try {
              controller.close();
            } catch {
              /* already closed by the client navigating away */
            }
            closed = true;
          }
        }
      })();

      ctx.waitUntil(work);
    },

    cancel() {
      // The user closed the tab or hit stop. The turn finishes in waitUntil so
      // its result is still saved; we simply stop writing.
      closed = true;
    },
  });

  return new Response(stream, {
    headers: {
      'content-type': 'text/event-stream; charset=utf-8',
      'cache-control': 'no-store, no-transform',
      connection: 'keep-alive',
      'x-accel-buffering': 'no',
    },
  });
}

export type { Anthropic };
