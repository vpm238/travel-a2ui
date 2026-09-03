/**
 * The MCP Apps bridge: how a view talks to the host it is embedded in.
 *
 * A view is an MCP *client* that reaches its host over `postMessage` rather
 * than over a socket, speaking ordinary JSON-RPC 2.0. The handshake matters and
 * is easy to get wrong by omission — a view that renders without it shows
 * nothing, because the surface never arrives:
 *
 *   1. the view sends `ui/initialize` and waits for the host's capabilities,
 *      theme and display mode;
 *   2. the view sends `ui/notifications/initialized`;
 *   3. *then* the host sends `ui/notifications/tool-input` with the arguments
 *      and `ui/notifications/tool-result` with the result — which is where the
 *      A2UI messages are, under `structuredContent`.
 *
 * Nothing before step 3 contains a surface. That is the whole difference
 * between this and the older MCP-UI convention, where the HTML arrived with the
 * payload already inside it: here the document is a *template*, fetched once,
 * and the data comes afterwards.
 *
 * Everything is defensive. A host that does not answer `ui/initialize` leaves
 * the view waiting forever, so there is a timeout and a fallback to the inlined
 * payload; a host that speaks the older convention never sends a notification
 * at all, and that same fallback is what makes one bundle serve both.
 */

export interface HostContext {
  theme?: 'light' | 'dark' | string;
  displayMode?: 'inline' | 'fullscreen' | 'pip' | string;
  maxHeight?: number;
  [key: string]: unknown;
}

type Handler = (params: Record<string, unknown>) => void;

interface Pending {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
}

export class HostBridge {
  private id = 0;
  private readonly pending = new Map<number, Pending>();
  private readonly handlers = new Map<string, Set<Handler>>();
  private readonly target: Window | null;

  /** What the host told us about itself, once `connect()` resolves. */
  context: HostContext = {};
  connected = false;

  constructor() {
    // A view is always framed. Outside a frame `parent === window`, and posting
    // to ourselves is harmless — the fallback path takes over.
    this.target = typeof window === 'undefined' ? null : window.parent;
    if (typeof window !== 'undefined') {
      window.addEventListener('message', (event) => this.receive(event.data));
    }
  }

  on(method: string, handler: Handler): () => void {
    const set = this.handlers.get(method) ?? new Set<Handler>();
    set.add(handler);
    this.handlers.set(method, set);
    return () => set.delete(handler);
  }

  /**
   * Runs the handshake.
   *
   * Resolves false rather than throwing when there is no host on the other end:
   * this is the ordinary case in an older host, and a view that treats it as an
   * error renders an error instead of the surface it was given inline.
   */
  async connect(timeoutMs = 2000): Promise<boolean> {
    try {
      const result = (await this.request(
        'ui/initialize',
        {
          appCapabilities: {},
          appInfo: { name: 'travel-a2ui-surface', version: '0.1.0' },
        },
        timeoutMs,
      )) as { hostContext?: HostContext } | undefined;

      this.context = result?.hostContext ?? {};
      this.connected = true;
      this.notify('ui/notifications/initialized', {});
      return true;
    } catch {
      return false;
    }
  }

  request(method: string, params: Record<string, unknown>, timeoutMs = 10_000): Promise<unknown> {
    if (!this.target) return Promise.reject(new Error('no host'));
    const id = ++this.id;

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out`));
      }, timeoutMs);

      this.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        reject: (reason) => {
          clearTimeout(timer);
          reject(reason);
        },
      });

      this.post({ jsonrpc: '2.0', id, method, params });
    });
  }

  notify(method: string, params: Record<string, unknown>): void {
    this.post({ jsonrpc: '2.0', method, params });
  }

  private post(message: unknown): void {
    try {
      this.target?.postMessage(message, '*');
    } catch {
      /* a host that forbids postMessage still gets a rendered surface */
    }
  }

  private receive(data: unknown): void {
    if (!data || typeof data !== 'object') return;
    const message = data as Record<string, unknown>;
    if (message['jsonrpc'] !== '2.0') return;

    // A reply to something we asked.
    if (typeof message['id'] === 'number' && !message['method']) {
      const waiting = this.pending.get(message['id'] as number);
      if (!waiting) return;
      this.pending.delete(message['id'] as number);
      if (message['error']) {
        const error = message['error'] as { message?: string };
        waiting.reject(new Error(error.message ?? 'host error'));
      } else {
        waiting.resolve(message['result']);
      }
      return;
    }

    const method = message['method'];
    if (typeof method !== 'string') return;
    for (const handler of this.handlers.get(method) ?? []) {
      handler((message['params'] ?? {}) as Record<string, unknown>);
    }
  }
}
