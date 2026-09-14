/**
 * Modality 3 — the generative home screen, built when it is asked for.
 *
 * No fixed dashboard. The layout itself is generated for where the trip stands:
 * stat tiles when there are numbers worth watching, a decision when one is
 * pending, weather and a map for context.
 *
 * It used to build itself — on opening this tab, and again beside the sidebar
 * on every turn that changed the shape of the trip. Both are gone. A dashboard
 * is a summary, and a conversation is where the trip is still being decided, so
 * rebuilding it mid-chat summarised something that did not exist yet; it also
 * cost a model call per turn for a surface nobody was looking at, and put stat
 * tiles and progress meters in front of a model whose job that turn was a date
 * picker.
 *
 * So it waits. The button below is the trigger, and by the time somebody presses
 * it there is a conversation and a trip to build from.
 */

import { useState } from 'react';
import { A2uiSurface, useSurface } from '@travel-a2ui/renderer';

import type { Agent } from '../useAgent.js';
import { Spinner } from './bits.js';

export function Home({ agent }: { agent: Agent }) {
  const [request, setRequest] = useState('');
  // Same reason as the sidebar: the dashboard arrives from a silent turn.
  const hasSurface = Boolean(useSurface(agent.store, 'home'));
  const canRun = Boolean(agent.apiKey) || Boolean(agent.meta?.keyProvided);

  /*
   * What a home screen *is* was a prose prompt in this file. It is the agent's
   * surface brief now, so all this sends is the surface — plus, when someone
   * types one, the extra thing they asked for, which is genuinely theirs.
   */
  const regenerate = (extra?: string) => void agent.drawSurface('home', extra);

  return (
    <section className="home" aria-label="Trip dashboard">
      <header className="home__head">
        <div>
          <h2>Your trip</h2>
          <p>Built from the conversation and what has been decided, when you ask for it.</p>
        </div>
        <div className="home__actions">
          {agent.liveSurface === 'home' ? <Spinner label="Laying out" /> : null}
          {hasSurface ? (
            <button
              type="button"
              className="button"
              onClick={() => regenerate()}
              disabled={agent.busy}
            >
              Rebuild
            </button>
          ) : null}
        </div>
      </header>

      {hasSurface ? (
        <div className="home__surface">
          <A2uiSurface store={agent.store} surfaceId="home" onEvent={agent.handleSurfaceEvent} />
        </div>
      ) : (
        <div className="home__placeholder">
          {canRun ? (
            <>
              <p>
                Nothing here yet. Plan something in the chat, then build this from
                it — the route, the dates, what is still open and what it costs.
              </p>
              <button
                type="button"
                className="button button--primary"
                onClick={() => regenerate()}
                disabled={agent.busy}
              >
                Build home page
              </button>
            </>
          ) : (
            <p>Add an API key to build the dashboard.</p>
          )}
        </div>
      )}

      <form
        className="home__ask"
        onSubmit={(event) => {
          event.preventDefault();
          const text = request.trim();
          if (!text || agent.busy) return;
          setRequest('');
          regenerate(text);
        }}
      >
        <input
          value={request}
          onChange={(event) => setRequest(event.target.value)}
          placeholder="Change the layout — “put the packing list on top”, “show me the budget as a chart”"
          aria-label="Change the dashboard"
        />
        <button type="submit" className="button" disabled={!request.trim() || agent.busy}>
          Rebuild
        </button>
      </form>
    </section>
  );
}
