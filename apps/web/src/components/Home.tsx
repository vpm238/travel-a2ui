/**
 * Modality 3 — the generative home screen.
 *
 * No fixed dashboard. The layout itself is generated for where the trip stands
 * today: stat tiles when there are numbers worth watching, a decision when one
 * is pending, weather and a map for context, and — when nothing is planned yet —
 * a single prompt instead of a grid of zeroes.
 *
 * It regenerates when the trip changes or the day does, and the traveler can ask
 * it to reconfigure in words, which is the part a hand-built dashboard cannot do.
 */

import { useEffect, useRef, useState } from 'react';
import { A2uiSurface, useSurface } from '@travel-a2ui/renderer';

import type { Agent } from '../useAgent.js';
import { Spinner } from './bits.js';

export function Home({ agent }: { agent: Agent }) {
  const [request, setRequest] = useState('');
  const built = useRef(false);
  // Same reason as the sidebar: the dashboard arrives from a silent turn.
  const hasSurface = Boolean(useSurface(agent.store, 'home'));
  const canRun = Boolean(agent.apiKey) || Boolean(agent.meta?.keyProvided);

  useEffect(() => {
    if (built.current || hasSurface || agent.busy || !canRun) return;
    built.current = true;
    void agent.drawSurface('home');
  }, [agent, canRun, hasSurface]);

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
          <p>Reassembled from what the agent knows, every time you open it.</p>
        </div>
        <div className="home__actions">
          {agent.liveSurface === 'home' ? <Spinner label="Laying out" /> : null}
          <button type="button" className="button" onClick={() => regenerate()} disabled={agent.busy}>
            Regenerate
          </button>
        </div>
      </header>

      {hasSurface ? (
        <div className="home__surface">
          <A2uiSurface store={agent.store} surfaceId="home" onEvent={agent.handleSurfaceEvent} />
        </div>
      ) : (
        <div className="home__placeholder">
          <p>
            {canRun
              ? 'Building your dashboard…'
              : 'Add an API key to generate the dashboard.'}
          </p>
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
