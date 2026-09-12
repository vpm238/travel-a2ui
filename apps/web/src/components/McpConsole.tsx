/**
 * Modality 4 — the MCP app.
 *
 * The same catalog and the same compiler, reached over the Model Context
 * Protocol instead of over our own API. This console is a client for it: it
 * lists the server's tools, calls one, and renders the A2UI that comes back.
 *
 * It exists to make the point concrete. The surface below is drawn from a
 * payload any MCP host could have received — Claude, Codex, anything that
 * speaks the protocol — which is what "the agent can hand you an interface"
 * means once it leaves this app.
 *
 * The interactions are live, too: the events fire into the same handler as
 * every other surface.
 */

import { useCallback, useEffect, useState } from 'react';
import { A2uiSurface } from '@travel-a2ui/renderer';
import type { A2uiMessage } from '@travel-a2ui/express';

import { mcp, type McpTool } from '../api.js';
import type { Agent } from '../useAgent.js';
import { Code, Disclosure, Spinner } from './bits.js';

/**
 * The example arguments a tool ships with, from `_meta.example`.
 *
 * This console used to keep its own table, and the entry for the headline tool
 * omitted the date `show_flight_options` requires — so the first button anyone
 * pressed answered with a refusal. A second copy of anything is a second thing
 * to get wrong; the server declares them now, and a test proves each one works.
 */
function exampleFor(tool: McpTool | undefined): Record<string, unknown> {
  const meta = (tool as { _meta?: { example?: unknown } } | undefined)?._meta;
  const example = meta?.example;
  return example && typeof example === 'object' ? (example as Record<string, unknown>) : {};
}

export function McpConsole({ agent }: { agent: Agent }) {
  // The app's own store, not a private one: an MCP surface is a surface like
  // any other, and putting it here means it shows up in the Wire tab beside
  // everything the agent drew.
  const store = agent.store;
  const [tools, setTools] = useState<McpTool[] | null>(null);
  const [selected, setSelected] = useState<string>('show_flight_options');
  const [argsText, setArgsText] = useState<string>('{}');
  const [surfaceId, setSurfaceId] = useState<string | null>(null);
  const [summary, setSummary] = useState<string>('');
  const [raw, setRaw] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    mcp
      .listTools()
      .then((result) => {
        setTools(result.tools);
        // Fill the box from the server's own example, so the console opens on a
        // call that works rather than on an empty object.
        setArgsText(
          JSON.stringify(exampleFor(result.tools.find((tool) => tool.name === selected)), null, 2),
        );
      })
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)));
    // Runs once: `selected` is only the initial choice here, and `choose` keeps
    // the box in step after that.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const choose = (name: string) => {
    setSelected(name);
    setArgsText(JSON.stringify(exampleFor(tools?.find((tool) => tool.name === name)), null, 2));
    setError(null);
  };

  const call = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      let args: Record<string, unknown>;
      try {
        args = JSON.parse(argsText || '{}') as Record<string, unknown>;
      } catch {
        setError('Arguments are not valid JSON.');
        return;
      }

      const result = await mcp.callTool(selected, args);
      const text = result.content.find((part) => part.type === 'text')?.text ?? '';
      setSummary(text);

      if (result.isError) {
        setError(text || 'The tool reported an error.');
        setSurfaceId(null);
        return;
      }

      const payload = result.structuredContent;
      if (!payload) return;

      // Two kinds of tool, and the difference is the architecture.
      //
      // A `show_*` tool returns A2UI: the server composed the surface and the
      // host renders it. A data tool returns *data* — flights, rates, a
      // forecast — and the host model composes the surface itself, which is
      // this project's actual thesis and until recently something only the
      // Gemini paths could do.
      //
      // Rendering has to branch, because a data result has no `messages` to
      // apply. It used to be assumed: selecting a data tool called
      // `store.apply(undefined)` and drew nothing, with nothing on screen to
      // say why.
      // Narrowed by shape rather than by a flag, because the shape is the
      // only thing a generic MCP host actually has to go on.
      const drawn = payload as { surfaceId?: unknown; messages?: unknown };
      if (Array.isArray(drawn.messages) && typeof drawn.surfaceId === 'string') {
        store.remove(drawn.surfaceId);
        store.apply(drawn.messages as A2uiMessage[]);
        setSurfaceId(drawn.surfaceId);
        setRaw(JSON.stringify(drawn.messages, null, 2));
        return;
      }

      // Data, not a surface. Shown as what it is: the JSON a host model
      // reads before deciding what to draw.
      setSurfaceId(null);
      setRaw(JSON.stringify(payload, null, 2));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }, [argsText, selected, store]);

  return (
    <section className="mcp" aria-label="MCP app console">
      <header className="mcp__head">
        <div>
          <h2>MCP app</h2>
          <p>
            Two kinds of tool, and the difference is the whole idea. The{' '}
            <strong>show_</strong> tools return a finished interface — one call, a good layout,
            nothing to compose. The <strong>data</strong> tools return flights and rates and
            forecasts, and the host model composes the surface itself from the component
            reference. Any MCP host — Claude, Codex, your own — can do either. This console is
            one such host.
          </p>
        </div>
        <code className="mcp__endpoint">POST {window.location.origin}/mcp</code>
      </header>

      <div className="mcp__grid">
        <div className="mcp__controls">
          <h3>Tools</h3>
          {tools === null && !error ? <Spinner label="Loading" /> : null}
          <ul className="mcp__tools">
            {(tools ?? []).map((tool) => (
              <li key={tool.name}>
                <button
                  type="button"
                  className={tool.name === selected ? 'is-active' : undefined}
                  onClick={() => choose(tool.name)}
                >
                  <strong>{tool.title ?? tool.name}</strong>
                  <span>{tool.description?.split('.')[0]}.</span>
                </button>
              </li>
            ))}
          </ul>

          <label className="mcp__args">
            <span>Arguments</span>
            <textarea
              value={argsText}
              spellCheck={false}
              rows={selected === 'render_a2ui_express' ? 14 : 8}
              onChange={(event) => setArgsText(event.target.value)}
            />
          </label>

          <button type="button" className="button button--primary" onClick={() => void call()} disabled={busy}>
            {busy ? 'Calling…' : `Call ${selected}`}
          </button>

          {error ? <p className="mcp__error">{error}</p> : null}
        </div>

        <div className="mcp__result">
          <h3>What the host receives</h3>
          {summary ? <p className="mcp__summary">{summary}</p> : null}

          {surfaceId ? (
            <>
              <div className="mcp__surface">
                <A2uiSurface store={store} surfaceId={surfaceId} onEvent={agent.handleSurfaceEvent} />
              </div>
              <Disclosure summary={<span>The A2UI payload ({raw.length.toLocaleString()} bytes)</span>}>
                <Code>{raw}</Code>
              </Disclosure>
            </>
          ) : (
            <p className="mcp__hint">
              Pick a tool and call it. The result carries a plain-text summary <em>and</em> an A2UI
              payload, so a host that cannot draw it still gets a usable answer.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
