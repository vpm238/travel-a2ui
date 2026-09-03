/**
 * The browser's half of the wire protocol.
 *
 * Two things worth knowing:
 *
 * 1. **The key never goes in a URL.** `EventSource` can only issue a GET with no
 *    custom headers, which would force the API key into a query string, where it
 *    lands in every access log between here and the Worker. So this reads the
 *    SSE stream out of a `fetch` POST body instead — more code, and the only
 *    version of this that is safe to deploy.
 *
 * 2. **A turn is cancellable.** The `AbortSignal` reaches the Worker, which
 *    stops writing; the turn itself finishes server-side so the transcript stays
 *    consistent for the next message.
 */

import type { A2uiMessage } from '@travel-a2ui/express';

export type SkillVariant = 'express-monolithic' | 'express-modular' | 'direct-json-monolithic';
export type SurfaceKind = 'inline' | 'sidebar' | 'home';

export type AgentEvent =
  | { type: 'start'; model: string; skill: SkillVariant; surfaceId: string }
  | { type: 'text'; delta: string; round?: number }
  | { type: 'ui'; surfaceId: string; messages: A2uiMessage[]; done: boolean }
  | { type: 'ui_error'; message: string; source: string }
  | { type: 'tool'; name: string; input: unknown; status: 'running' }
  | { type: 'tool_result'; name: string; result: unknown; isError: boolean }
  | { type: 'trip'; trip: Record<string, unknown> }
  | {
      type: 'usage';
      inputTokens: number;
      outputTokens: number;
      cacheReadTokens: number;
      cacheWriteTokens: number;
    }
  | { type: 'error'; message: string; retryable: boolean }
  | { type: 'done'; stopReason: string | null };

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
  destinations: Array<{ city: string; country: string; airport: string; summary: string }>;
  mcpEndpoint: string;
  keyProvided: boolean;
  /** Which agent runtimes this deployment knows about. */
  backends?: BackendOption[];
  /** Which runtime answered this request. */
  runtime?: BackendId;
}

export interface ChatRequest {
  sessionId: string;
  message: string;
  surface: SurfaceKind;
  surfaceId?: string;
  skill: SkillVariant;
  model: string;
  effort?: 'low' | 'medium' | 'high';
  surfaceState?: Record<string, unknown>;
}

/**
 * Which agent runtime is answering.
 *
 * Both speak the same wire protocol, and that is the point being made: the
 * components, the catalog, the skills and this front end are one build, and the
 * thing running the agent loop underneath is swappable at runtime.
 *
 *   worker         the Cloudflare Worker this app is served from. Same origin,
 *                  nothing to configure, one deploy.
 *   managed-agent  the Python backend in `backends/claude-managed-agent`, which
 *                  hands the loop to an Anthropic-hosted Managed Agent. Runs
 *                  somewhere else, so it needs an origin.
 */
export type BackendId = 'worker' | 'managed-agent';

export interface BackendOption {
  id: BackendId;
  label: string;
  note: string;
  /** Empty means "same origin as this app". */
  origin: string;
}

/**
 * Where API calls go right now.
 *
 * Empty is same-origin. `VITE_API_ORIGIN` still works as a build-time default —
 * it is what the standalone front end uses when it is not served by the Worker
 * at all — but the picker in the header overrides it per session.
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

export async function fetchMeta(): Promise<Meta> {
  const response = await fetch(api('/api/meta'));
  if (!response.ok) throw new Error(`Could not load app metadata (${response.status}).`);
  return (await response.json()) as Meta;
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
  if (options.apiKey) headers['x-anthropic-key'] = options.apiKey;

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

// ------------------------------------------------------------------- MCP

export interface McpTool {
  name: string;
  title?: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
}

let mcpRequestId = 0;

async function mcpCall<T>(method: string, params?: Record<string, unknown>): Promise<T> {
  const response = await fetch(api('/mcp'), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: ++mcpRequestId, method, params }),
  });
  const body = (await response.json()) as { result?: T; error?: { message: string } };
  if (body.error) throw new Error(body.error.message);
  return body.result as T;
}

export const mcp = {
  listTools: () => mcpCall<{ tools: McpTool[] }>('tools/list'),
  callTool: (name: string, args: Record<string, unknown>) =>
    mcpCall<{
      content: Array<{ type: string; text?: string; resource?: { uri: string; mimeType: string; text: string } }>;
      structuredContent?: { surfaceId: string; catalogId: string; messages: A2uiMessage[] };
      isError?: boolean;
    }>('tools/call', { name, arguments: args }),
};
