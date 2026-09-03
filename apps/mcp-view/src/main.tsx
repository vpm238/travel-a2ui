/**
 * The A2UI renderer, packaged for an MCP host.
 *
 * Same React components as the web app — literally the same package, not a
 * reimplementation. The interesting part is that it serves two host
 * conventions from one bundle, because they hand over a surface in opposite
 * ways:
 *
 *   **MCP Apps.** The host reads this document once from `ui://travel-a2ui/surface`
 *   as a *template* and then sends each tool result over the postMessage
 *   bridge. Nothing arrives with the document; the surface comes after the
 *   handshake. This is what Claude speaks.
 *
 *   **MCP-UI.** The host takes a `text/html` resource out of each tool result
 *   with the payload already inlined in a `<script type="application/json">`.
 *
 * So: try the bridge, fall back to the inlined payload. A host that answers the
 * handshake never has an inlined payload to read, and a host that inlines never
 * answers the handshake, so the two paths cannot collide.
 *
 * Interactions go back as `ui/message` — a user turn in the host's own
 * conversation, which is exactly what an A2UI event is: the traveler saying
 * something in the interface rather than in prose.
 */

import { StrictMode, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { A2uiSurface, SurfaceStore, type A2uiEvent } from '@travel-a2ui/renderer';
import type { A2uiMessage } from '@travel-a2ui/express';

import '@travel-a2ui/renderer/styles.css';
import './view.css';

import { HostBridge } from './bridge.js';

interface Payload {
  messages: A2uiMessage[];
  surfaceId: string;
  summary?: string;
}

const EMPTY: Payload = { messages: [], surfaceId: '', summary: '' };

/** The MCP-UI path: the payload was inlined into the document. */
function readInlinePayload(): Payload | null {
  const element = document.getElementById('a2ui-payload');
  if (!element?.textContent?.trim()) return null;
  try {
    const parsed = JSON.parse(element.textContent) as Payload;
    return parsed.messages?.length ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * The A2UI messages inside a tool result.
 *
 * `structuredContent` is where they belong and where the composed tools put
 * them. The embedded-resource path is the same server talking to a host that
 * asked for the payload as a resource, and costs three lines to also accept.
 */
function payloadFromResult(result: unknown): Payload | null {
  if (!result || typeof result !== 'object') return null;
  const record = result as Record<string, unknown>;

  const structured = record['structuredContent'] as Record<string, unknown> | undefined;
  if (Array.isArray(structured?.['messages'])) {
    return {
      messages: structured['messages'] as A2uiMessage[],
      surfaceId: String(structured['surfaceId'] ?? 'mcp'),
      summary: typeof record['summary'] === 'string' ? record['summary'] : '',
    };
  }

  const content = record['content'];
  if (Array.isArray(content)) {
    for (const part of content) {
      const resource = (part as Record<string, unknown>)?.['resource'] as
        | Record<string, unknown>
        | undefined;
      const mime = String(resource?.['mimeType'] ?? '');
      if (!mime.includes('a2ui') || typeof resource?.['text'] !== 'string') continue;
      try {
        const messages = JSON.parse(resource['text']) as A2uiMessage[];
        if (Array.isArray(messages) && messages.length > 0) {
          const created = messages.find((entry) => 'createSurface' in (entry as object)) as
            | { createSurface?: { surfaceId?: string } }
            | undefined;
          return { messages, surfaceId: created?.createSurface?.surfaceId ?? 'mcp' };
        }
      } catch {
        /* a resource we cannot parse is not the surface we wanted */
      }
    }
  }

  return null;
}

const bridge = new HostBridge();

function View() {
  const [payload, setPayload] = useState<Payload>(() => readInlinePayload() ?? EMPTY);
  const [waiting, setWaiting] = useState(() => readInlinePayload() === null);

  const store = useMemo(() => new SurfaceStore(), []);

  useEffect(() => {
    // Register before connecting: the host is allowed to send the result the
    // moment it sees `initialized`, and a listener attached afterwards misses
    // it — which looks exactly like a view that does not work.
    const off = bridge.on('ui/notifications/tool-result', (params) => {
      const next = payloadFromResult(params['result'] ?? params);
      if (next) {
        setPayload(next);
        setWaiting(false);
      }
    });

    void bridge.connect().then((connected) => {
      // No host on the other end and nothing inlined either: there is nothing
      // to wait for, so say so rather than spinning forever.
      if (!connected && readInlinePayload() === null) setWaiting(false);
    });

    return off;
  }, []);

  useEffect(() => {
    if (payload.messages.length > 0) store.apply(payload.messages);
  }, [payload, store]);

  // The frame does not size itself. Both conventions are told, because a host
  // that ignores one usually understands the other.
  useEffect(() => {
    const report = () => {
      const height = Math.ceil(document.documentElement.scrollHeight);
      bridge.notify('ui/notifications/size-changed', { height });
      try {
        window.parent?.postMessage({ type: 'ui/size-change', payload: { height } }, '*');
      } catch {
        /* a host that forbids postMessage still gets a rendered surface */
      }
    };
    report();
    const observer = new ResizeObserver(report);
    observer.observe(document.documentElement);
    return () => observer.disconnect();
  }, [payload]);

  /**
   * An interaction becomes the user's next turn.
   *
   * `ui/message` is the MCP Apps way to put something in the conversation, and
   * it is the right shape for this: tapping a flight *is* the traveler
   * answering, phrased in the interface instead of in prose. The legacy
   * postMessage shapes go out too, for a host that reads those.
   */
  const onEvent = (event: A2uiEvent) => {
    const detail = {
      surfaceId: event.surfaceId,
      name: event.name,
      context: event.context,
      dataModel: event.dataModel,
    };

    const described = Object.entries(event.context ?? {})
      .filter(([, value]) => value !== null && value !== undefined && value !== '')
      .map(([key, value]) => `${key}: ${JSON.stringify(value)}`)
      .join(', ');

    if (bridge.connected) {
      void bridge
        .request('ui/message', {
          role: 'user',
          content: `[interface] ${event.name}${described ? ` (${described})` : ''}`,
        })
        .catch(() => undefined);
      // So the model can read the state behind the tap, not just the tap.
      bridge.notify('ui/update-model-context', { structuredContent: detail });
    }

    for (const message of [
      { type: 'ui/action', payload: { type: 'intent', intent: event.name, params: detail } },
      { type: 'a2ui.event', payload: detail },
    ]) {
      try {
        window.parent?.postMessage(message, '*');
      } catch {
        /* nothing to do; the surface stays usable */
      }
    }
  };

  if (payload.messages.length === 0) {
    return (
      <p className="view__empty">
        {waiting ? 'Loading the surface…' : payload.summary || 'This tool returned no interface to render.'}
      </p>
    );
  }

  return (
    <div className="view">
      <A2uiSurface store={store} surfaceId={payload.surfaceId} onEvent={onEvent} />
    </div>
  );
}

const container = document.getElementById('root');
if (container) {
  container.innerHTML = '';
  createRoot(container).render(
    <StrictMode>
      <View />
    </StrictMode>,
  );
}
