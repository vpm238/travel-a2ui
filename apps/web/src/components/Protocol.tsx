/**
 * The mechanism, shown.
 *
 * Every live surface, in both forms: the A2UI JSON the renderer holds, and the
 * Express that produces it. The Express is recovered by the A2UI SDK's own
 * decompiler, on the server (`POST /api/express`) — this view used to carry a
 * TypeScript port of it, and of the compiler and the schema crawler it leaned
 * on, so that a page which only *shows* the protocol shipped one. It is usually
 * about a third the size of the JSON, which is the argument for the notation in
 * one number rather than one paragraph.
 *
 * This is a debugging view that earns its place in the product: "what did the
 * model actually emit" is the first question anyone asks about generative UI,
 * and here the answer is one tab away.
 */

import { useEffect, useMemo, useState } from 'react';

import { decompile } from '../api.js';
import type { Agent } from '../useAgent.js';
import { Code, Empty } from './bits.js';
import { useSurfaces } from './SurfaceView.js';

export function Protocol({ agent }: { agent: Agent }) {
  const [selected, setSelected] = useState<string | null>(null);
  const version = useSurfaces(agent.store);
  const ids = agent.store.ids();
  const active = selected && ids.includes(selected) ? selected : (ids[ids.length - 1] ?? null);

  const { json, envelope, dataModel } = useMemo(() => {
    const snapshot = active ? agent.store.snapshot(active) : undefined;
    if (!snapshot) return { json: '', envelope: null, dataModel: {} as Record<string, unknown> };
    // The server's own version, not a literal: this view exists to show what
    // really went over the wire.
    const message = { version: agent.meta?.protocolVersion ?? '1.0', createSurface: snapshot };
    return {
      json: JSON.stringify(message, null, 2),
      envelope: message,
      dataModel: (snapshot['dataModel'] ?? {}) as Record<string, unknown>,
    };
    // `version` changes when any message lands, which is when this is stale.
  }, [active, version, agent.store, agent.meta?.protocolVersion]); // eslint-disable-line react-hooks/exhaustive-deps

  const [express, setExpress] = useState<{ for: string; text: string; failed: boolean } | null>(null);
  useEffect(() => {
    if (!envelope) return;
    let live = true;
    const handle = setTimeout(() => {
      decompile([envelope])
        .then((text) => live && setExpress({ for: json, text, failed: false }))
        .catch(() => live && setExpress({ for: json, text: '', failed: true }));
    }, 150);
    return () => {
      live = false;
      clearTimeout(handle);
    };
  }, [json]); // eslint-disable-line react-hooks/exhaustive-deps
  const current = express && express.for === json ? express : null;

  const ratio =
    json && current?.text ? Math.round((1 - current.text.length / json.length) * 100) : null;

  return (
    <section className="protocol" aria-label="Protocol inspector">
      <header className="protocol__head">
        <div>
          <h2>On the wire</h2>
          <p>
            What the agent wrote, and what the host received. Same surface, two representations.
          </p>
        </div>
      </header>

      {ids.length === 0 ? (
        <Empty title="No surfaces yet">
          Start a conversation, build the sidebar, or open the home screen — anything the agent
          draws shows up here.
        </Empty>
      ) : (
        <>
          <nav className="protocol__tabs" aria-label="Surfaces">
            {ids.map((id) => (
              <button
                key={id}
                type="button"
                className={id === active ? 'is-active' : undefined}
                onClick={() => setSelected(id)}
              >
                {id}
              </button>
            ))}
          </nav>

          <div className="protocol__panes">
            <div className="protocol__pane">
              <h3>
                A2UI Express
                {ratio !== null ? <span className="protocol__stat">{ratio}% smaller</span> : null}
              </h3>
              {current?.text ? (
                <Code>{current.text}</Code>
              ) : (
                <p className="protocol__hint">
                  {current?.failed ? 'This surface did not decompile.' : 'Decompiling…'}
                </p>
              )}
            </div>

            <div className="protocol__pane">
              <h3>
                A2UI JSON
                <span className="protocol__stat">{json.length.toLocaleString()} bytes</span>
              </h3>
              <Code>{json}</Code>
            </div>
          </div>

          {Object.keys(dataModel).length > 0 ? (
            <div className="protocol__pane">
              <h3>Data model</h3>
              <p className="protocol__hint">
                What the user has changed on screen. The next agent turn reads exactly this.
              </p>
              <Code>{JSON.stringify(dataModel, null, 2)}</Code>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
