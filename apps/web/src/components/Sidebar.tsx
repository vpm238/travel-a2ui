/**
 * Modality 2 — the sidebar.
 *
 * One surface, id `sidebar`, that persists across turns and is replaced rather
 * than appended to. Where the inline card answers the message, this panel holds
 * the controls for the trip as a whole: dates, party size, budget, filters, what
 * has been chosen.
 *
 * The interesting property is that it is *context-aware*: it is regenerated when
 * the trip changes, so a panel that showed destination options becomes a panel
 * of flight filters once a destination is settled. Nothing here decides that —
 * the agent does, from the trip state.
 */

import { useEffect, useRef } from 'react';
import { A2uiSurface, useSurface } from '@travel-a2ui/renderer';

import type { Agent } from '../useAgent.js';
import { Spinner } from './bits.js';

/** Fingerprint of the decisions that should trigger a rebuild. */
function tripSignature(trip: Record<string, unknown>): string {
  const keys = ['destination', 'startDate', 'endDate', 'travelers', 'budget', 'selectedFlight', 'selectedHotel'];
  return keys.map((key) => `${key}=${String(trip[key] ?? '')}`).join('|');
}

export function Sidebar({ agent }: { agent: Agent }) {
  const signature = tripSignature(agent.trip);
  const lastBuilt = useRef<string | null>(null);
  // Subscribe rather than reading the store during render: the panel arrives
  // from a silent turn, which changes nothing else this component watches.
  const hasSurface = Boolean(useSurface(agent.store, 'sidebar'));

  useEffect(() => {
    // Rebuild when the trip's shape changes, not on every token. The guard is a
    // ref rather than state so a rebuild cannot trigger its own rebuild.
    if (agent.busy) return;
    if (!agent.apiKey && !agent.meta?.keyProvided) return;
    if (lastBuilt.current === signature) return;
    if (signature === tripSignature({}) && !hasSurface) return;

    lastBuilt.current = signature;
    void agent.send(
      'Rebuild the sidebar for where the trip stands now. Controls only — no prose.',
      { surface: 'sidebar', surfaceId: 'sidebar', silent: true },
    );
  }, [agent, hasSurface, signature]);

  const build = () => {
    lastBuilt.current = signature;
    void agent.send('Build the sidebar for this trip.', {
      surface: 'sidebar',
      surfaceId: 'sidebar',
      silent: true,
    });
  };

  return (
    <aside className="sidebar" aria-label="Trip controls">
      <header className="sidebar__head">
        <h2>Refine</h2>
        {agent.liveSurface === 'sidebar' ? <Spinner /> : null}
      </header>

      {hasSurface ? (
        <div className="sidebar__body">
          <A2uiSurface store={agent.store} surfaceId="sidebar" onEvent={agent.handleSurfaceEvent} />
        </div>
      ) : (
        <div className="sidebar__placeholder">
          <p>
            A control panel the agent builds for whatever stage the trip is at — dates and party
            size at first, flight and budget filters once there is a destination.
          </p>
          <button type="button" className="button" onClick={build} disabled={agent.busy}>
            Build the panel
          </button>
        </div>
      )}

      {Object.keys(agent.trip).length > 0 ? (
        <div className="sidebar__trip">
          <h3>Decided so far</h3>
          <dl>
            {Object.entries(agent.trip).map(([key, value]) => (
              <div key={key}>
                <dt>{key.replace(/([A-Z])/g, ' $1').toLowerCase()}</dt>
                <dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
    </aside>
  );
}
