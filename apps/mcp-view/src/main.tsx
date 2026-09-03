/**
 * The A2UI renderer, packaged for an MCP host.
 *
 * Same React components as the web app — literally the same package, not a
 * reimplementation — built into one self-contained HTML file. An MCP tool
 * result carries it as a `text/html` resource, the host renders it in an
 * iframe, and the user gets real flight cards instead of a paragraph about
 * flights.
 *
 * Three constraints shape this file, all of them from the sandbox:
 *
 * 1. **No network.** The payload is inlined into the document before it is
 *    handed over. Nothing here fetches anything.
 * 2. **No host API.** Interactions are posted to the parent frame with
 *    `postMessage`. A host that listens gets the event; one that does not is
 *    unharmed, and the surface still reads correctly.
 * 3. **Unknown size.** The frame is whatever the host makes it, so the document
 *    measures itself and tells the parent how tall it wants to be.
 */

import { StrictMode, useEffect, useMemo } from 'react';
import { createRoot } from 'react-dom/client';
import { A2uiSurface, SurfaceStore, type A2uiEvent } from '@travel-a2ui/renderer';
import type { A2uiMessage } from '@travel-a2ui/express';

import '@travel-a2ui/renderer/styles.css';
import './view.css';

interface Payload {
  messages: A2uiMessage[];
  surfaceId: string;
  summary?: string;
}

function readPayload(): Payload {
  const element = document.getElementById('a2ui-payload');
  if (!element?.textContent) return { messages: [], surfaceId: '', summary: '' };
  try {
    return JSON.parse(element.textContent) as Payload;
  } catch {
    return { messages: [], surfaceId: '', summary: '' };
  }
}

/**
 * Tells the parent frame how tall the content is.
 *
 * An iframe does not size itself, so without this the surface is either clipped
 * or floating in whitespace. Hosts that implement `ui/size-change` resize;
 * others ignore it.
 */
function useReportHeight(): void {
  useEffect(() => {
    const post = () => {
      const height = Math.ceil(document.documentElement.scrollHeight);
      try {
        window.parent?.postMessage({ type: 'ui/size-change', payload: { height } }, '*');
      } catch {
        /* a host that forbids postMessage still gets a rendered surface */
      }
    };

    post();
    const observer = new ResizeObserver(post);
    observer.observe(document.documentElement);
    return () => observer.disconnect();
  }, []);
}

function View() {
  const payload = useMemo(readPayload, []);
  const store = useMemo(() => {
    const created = new SurfaceStore();
    if (payload.messages.length > 0) created.apply(payload.messages);
    return created;
  }, [payload]);

  useReportHeight();

  const onEvent = (event: A2uiEvent) => {
    // The MCP-UI convention: the host forwards this to its model as a prompt or
    // a tool call. Both shapes are sent — `ui/action` for hosts that speak it,
    // and a plain `a2ui.event` for anything bespoke reading our messages.
    const detail = {
      surfaceId: event.surfaceId,
      name: event.name,
      context: event.context,
      dataModel: event.dataModel,
    };
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
        {payload.summary || 'This tool returned no interface to render.'}
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
