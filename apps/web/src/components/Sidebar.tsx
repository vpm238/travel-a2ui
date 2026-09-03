/**
 * Modality 2 — the panel.
 *
 * One surface, id `sidebar`, persistent across turns and replaced rather than
 * appended to. Where the inline card asks the question, this shows the answers:
 * the route stop by stop, the flight and stay chosen, the dates, what it comes
 * to.
 *
 * **It is read-only**, and that is a design decision rather than a limitation.
 * It used to carry controls, which meant two places could change the same value
 * and the conversation had no record of which one did. Now deciding happens in
 * one place — inline, in the conversation — and this is the record. The panel's
 * only interaction is *Change*, which releases a decision and re-opens it
 * inline, pre-filled.
 *
 * Values sync into it from the trip with no model in the path, so changing the
 * route on an inline card updates it immediately. The agent is only asked to
 * rebuild when the panel should be a different *shape*.
 */

import { useEffect, useRef } from 'react';
import { A2uiSurface, useSurface } from '@travel-a2ui/renderer';

import type { Agent } from '../useAgent.js';
import { Spinner } from './bits.js';
import { TripPlan } from './TripPlan.js';

/**
 * Fingerprint of the decisions that should make the panel a *different panel*.
 *
 * Deliberately not every trip field. Values sync into the panel live — change
 * the departure airport on an inline card and the sidebar's origin updates
 * immediately, with no model in the path. What warrants a rebuild is the panel
 * needing different *controls*: once there is a destination it should show
 * flight filters, once a flight is chosen it should show what is left to book.
 *
 * Rebuilding on a slider value would mean a model turn every time someone
 * dragged something, which is both slow and pointless.
 */
function tripSignature(trip: Record<string, unknown>): string {
  const keys = ['destination', 'selectedFlight', 'selectedHotel'];
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
      'Rebuild the panel for where the trip stands now: what is settled, with a Change button ' +
        'on each decision. Read-only — no editors, no prose.',
      { surface: 'sidebar', surfaceId: 'sidebar', silent: true },
    );
  }, [agent, hasSurface, signature]);

  const build = () => {
    lastBuilt.current = signature;
    void agent.send('Build the panel for this trip: what is settled so far, read-only.', {
      surface: 'sidebar',
      surfaceId: 'sidebar',
      silent: true,
    });
  };

  return (
    <aside className="sidebar" aria-label="Trip controls">
      <header className="sidebar__head">
        <h2>The trip</h2>
        {agent.liveSurface === 'sidebar' ? <Spinner /> : null}
      </header>

      {hasSurface ? (
        <div className="sidebar__body">
          {/* No PendingEdits: there is nothing to edit here. The panel shows
              what is settled, and its only interaction is asking to change
              something — which re-opens it in the conversation. */}
          <A2uiSurface store={agent.store} surfaceId="sidebar" onEvent={agent.handleSurfaceEvent} />
        </div>
      ) : (
        <div className="sidebar__placeholder">
          <p>
            What you have settled, as you settle it — the route, the flight, where you are
            staying, what it comes to. Read-only on purpose: changing something sends it back
            to the conversation, pre-filled, so there is one place to decide and one record of
            when you did.
          </p>
          <button type="button" className="button" onClick={build} disabled={agent.busy}>
            Build the panel
          </button>
        </div>
      )}

      <TripPlan trip={agent.trip} />

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
