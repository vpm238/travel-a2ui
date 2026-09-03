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

import { mcp, type McpTool } from '../api.js';
import type { Agent } from '../useAgent.js';
import { Code, Disclosure, Spinner } from './bits.js';

/** Reasonable starting arguments so the console is useful on first click. */
const SAMPLE_ARGS: Record<string, Record<string, unknown>> = {
  show_flight_options: { destination: 'Madrid', origin: 'JFK', travelers: 2, cabin: 'economy' },
  show_hotel_options: { destination: 'Madrid', nights: 6, maxNightly: 260 },
  show_itinerary: { destination: 'Lisbon', days: 3 },
  show_trip_dashboard: { destination: 'Madrid', nights: 6, travelers: 2, budget: 2600, spent: 1320 },
  show_price_summary: { destination: 'Tokyo', travelers: 2, nights: 7 },
  render_a2ui_express: {
    surfaceId: 'mcp-custom',
    source: [
      'head = Text("Weekend in Lisbon", variant="h2")',
      'a1 = ActivityItem("Alfama at dawn", "07:30", category="sight", note="Before the tour groups")',
      'a2 = ActivityItem("Time Out Market", "11:30", category="food", duration="1h")',
      'day = ItineraryDay("Saturday", [a1, a2], date="Sat 18 Apr", summary="Slow start, long lunch")',
      'root = Column([head, day])',
    ].join('\n'),
  },
};

export function McpConsole({ agent }: { agent: Agent }) {
  // The app's own store, not a private one: an MCP surface is a surface like
  // any other, and putting it here means it shows up in the Wire tab beside
  // everything the agent drew.
  const store = agent.store;
  const [tools, setTools] = useState<McpTool[] | null>(null);
  const [selected, setSelected] = useState<string>('show_flight_options');
  const [argsText, setArgsText] = useState<string>(
    JSON.stringify(SAMPLE_ARGS['show_flight_options'], null, 2),
  );
  const [surfaceId, setSurfaceId] = useState<string | null>(null);
  const [summary, setSummary] = useState<string>('');
  const [raw, setRaw] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    mcp
      .listTools()
      .then((result) => setTools(result.tools))
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, []);

  const choose = (name: string) => {
    setSelected(name);
    setArgsText(JSON.stringify(SAMPLE_ARGS[name] ?? {}, null, 2));
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
      if (payload) {
        store.remove(payload.surfaceId);
        store.apply(payload.messages);
        setSurfaceId(payload.surfaceId);
        setRaw(JSON.stringify(payload.messages, null, 2));
      }
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
            Tools that return interfaces instead of text. Any MCP host — Claude, Codex, your own —
            can call these and render what comes back. This console is one such host.
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
