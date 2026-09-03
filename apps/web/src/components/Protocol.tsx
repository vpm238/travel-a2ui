/**
 * The mechanism, shown.
 *
 * Every live surface, in both forms: the A2UI JSON the host actually holds, and
 * the Express that produces it — recovered by running the decompiler over the
 * store. The Express is usually about a third the size, which is the argument
 * for the notation in one number rather than one paragraph.
 *
 * This is a debugging view that earns its place in the product: "what did the
 * model actually emit" is the first question anyone asks about generative UI,
 * and here the answer is one tab away.
 */

import { useEffect, useMemo, useState } from 'react';
import { ExpressDecompiler, type CatalogSchema } from '@travel-a2ui/express';
import { useSurface } from '@travel-a2ui/renderer';

import { catalogUrl } from '../api.js';
import type { Agent } from '../useAgent.js';
import { Code, Empty } from './bits.js';

export function Protocol({ agent }: { agent: Agent }) {
  const [catalog, setCatalog] = useState<CatalogSchema | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    fetch(catalogUrl())
      .then((response) => response.json() as Promise<CatalogSchema>)
      .then(setCatalog)
      .catch(() => setCatalog(null));
  }, []);

  // Subscribing keeps the list fresh as surfaces arrive mid-stream.
  useSurface(agent.store, selected ?? '');
  const ids = agent.store.ids();
  const active = selected && ids.includes(selected) ? selected : (ids[ids.length - 1] ?? null);
  const surface = active ? agent.store.get(active) : undefined;

  const { json, express } = useMemo(() => {
    if (!surface) return { json: '', express: '' };

    const envelope = {
      version: 'v0.9.1',
      createSurface: {
        surfaceId: surface.id,
        catalogId: surface.catalogId || catalog?.catalogId || '',
        components: [...surface.components.values()],
        ...(Object.keys(surface.dataModel).length > 0 ? { dataModel: surface.dataModel } : {}),
      },
    };

    const rendered = JSON.stringify(envelope, null, 2);
    if (!catalog) return { json: rendered, express: '' };

    try {
      return {
        json: rendered,
        express: new ExpressDecompiler(catalog).decompile(envelope as never),
      };
    } catch {
      return { json: rendered, express: '' };
    }
  }, [catalog, surface]);

  const ratio =
    json && express ? Math.round((1 - express.length / json.length) * 100) : null;

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
              {express ? (
                <Code>{express}</Code>
              ) : (
                <p className="protocol__hint">
                  {catalog ? 'This surface did not decompile.' : 'Loading the catalog…'}
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

          {surface && Object.keys(surface.dataModel).length > 0 ? (
            <div className="protocol__pane">
              <h3>Data model</h3>
              <p className="protocol__hint">
                What the user has changed on screen. The next agent turn reads exactly this.
              </p>
              <Code>{JSON.stringify(surface.dataModel, null, 2)}</Code>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
