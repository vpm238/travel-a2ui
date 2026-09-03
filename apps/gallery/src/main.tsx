/**
 * A gallery of real A2UI surfaces, with no backend behind it.
 *
 * Every surface here was compiled at build time from the catalog's own examples
 * by the same compiler the agent's output goes through, and rendered by the same
 * React components the app and the MCP plugin use. So it is not a mockup of the
 * product — it is the product's renderer, with a fixed set of inputs instead of
 * a live model.
 *
 * The event log is the part worth watching. Click a flight and you see exactly
 * what would reach the agent as your next turn: the event name, the context the
 * component bound into it, and the surface's data model. That round trip is the
 * whole protocol, and it is easier to believe when you can watch it happen.
 */

import { useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { A2uiSurface, SurfaceStore, type A2uiEvent } from '@travel-a2ui/renderer';
import type { A2uiMessage } from '@travel-a2ui/express';

import '@travel-a2ui/renderer/styles.css';
import './gallery.css';

import generated from './surfaces.generated.json';

interface Surface {
  id: string;
  surfaceId: string;
  title: string;
  flow: 'inline' | 'sidebar' | 'home';
  description: string;
  express: string;
  messages: A2uiMessage[];
  bytes: number;
}

const SURFACES = generated as unknown as Surface[];

const FLOW_NOTE: Record<Surface['flow'], string> = {
  inline: 'Drawn under the reply it answers. One job, and an action that continues the conversation.',
  sidebar: 'A panel beside the conversation that replaces itself as the trip changes. Controls, not content.',
  home: 'Where the trip stands today, laid out for what matters now rather than to a fixed template.',
};

interface LoggedEvent {
  at: string;
  name: string;
  context: Record<string, unknown>;
  dataModel: Record<string, unknown>;
}

function Gallery() {
  const [activeId, setActiveId] = useState(SURFACES[0]!.id);
  const [log, setLog] = useState<LoggedEvent[]>([]);
  const [showSource, setShowSource] = useState(false);

  // One store for everything: surfaces are addressed by id, and sharing the
  // store is what lets a value edited on one show up on another.
  const store = useMemo(() => {
    const created = new SurfaceStore();
    for (const surface of SURFACES) created.apply(surface.messages);
    return created;
  }, []);

  const active = SURFACES.find((surface) => surface.id === activeId)!;
  const expressBytes = active.express.length;
  const saved = Math.round((1 - expressBytes / active.bytes) * 100);

  const onEvent = (event: A2uiEvent) => {
    setLog((current) =>
      [
        {
          at: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          name: event.name,
          context: event.context,
          dataModel: event.dataModel,
        },
        ...current,
      ].slice(0, 8),
    );
  };

  return (
    <div className="gallery">
      <header className="gallery__head">
        <div>
          <h1>A2UI surfaces</h1>
          <p>
            Real components, compiled from the catalog's own examples by the real compiler. There is
            no model behind this page — everything is interactive, and every interaction is logged
            below exactly as the agent would receive it.
          </p>
        </div>
      </header>

      <nav className="gallery__tabs" aria-label="Surfaces">
        {SURFACES.map((surface) => (
          <button
            key={surface.id}
            type="button"
            aria-current={surface.id === activeId}
            className={surface.id === activeId ? 'is-active' : undefined}
            onClick={() => setActiveId(surface.id)}
          >
            <span className={`gallery__flow gallery__flow--${surface.flow}`}>{surface.flow}</span>
            {surface.title}
          </button>
        ))}
      </nav>

      <div className="gallery__body">
        <section className="gallery__stage" aria-label={active.title}>
          <div className="gallery__meta">
            <p>{active.description || FLOW_NOTE[active.flow]}</p>
            <button type="button" className="gallery__toggle" onClick={() => setShowSource((v) => !v)}>
              {showSource ? 'Hide the source' : 'Show the A2UI Express'}
            </button>
          </div>

          {showSource ? (
            <div className="gallery__source">
              <div className="gallery__sourceHead">
                <span>A2UI Express</span>
                <span>
                  {expressBytes.toLocaleString()} bytes · {saved}% smaller than the{' '}
                  {active.bytes.toLocaleString()}-byte JSON it compiles to
                </span>
              </div>
              <pre>
                <code>{active.express}</code>
              </pre>
            </div>
          ) : null}

          <div className={`gallery__surface gallery__surface--${active.flow}`}>
            <A2uiSurface store={store} surfaceId={active.surfaceId} onEvent={onEvent} />
          </div>
        </section>

        <aside className="gallery__log" aria-label="Events">
          <h2>What the agent would receive</h2>
          {log.length === 0 ? (
            <p className="gallery__hint">
              Tap a flight, move a slider, tick a box. Each interaction becomes the user's next turn,
              phrased in the interface instead of in prose.
            </p>
          ) : (
            <ol>
              {log.map((entry, index) => (
                <li key={index}>
                  <div className="gallery__logHead">
                    <strong>{entry.name}</strong>
                    <span>{entry.at}</span>
                  </div>
                  {Object.keys(entry.context).length > 0 ? (
                    <pre>
                      <code>{JSON.stringify(entry.context, null, 2)}</code>
                    </pre>
                  ) : (
                    <p className="gallery__hint">no context</p>
                  )}
                </li>
              ))}
            </ol>
          )}
        </aside>
      </div>

      <footer className="gallery__foot">
        <span>
          A2UI v0.9.1 · {SURFACES.length} surfaces · the same renderer the app and the MCP plugin use
        </span>
      </footer>
    </div>
  );
}

const container = document.getElementById('root');
if (container) createRoot(container).render(<Gallery />);
