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
 * There is no React in it any more — not a checklist, not a key/value list of
 * what has been decided. All of it is A2UI the agent composed, which is what
 * makes the panel portable: the Flutter renderer draws this exact panel
 * with no travel-specific code, because there is none left to port.
 *
 * Values reach it as `updateDataModel` from the server, so changing the route on
 * an inline card moves the panel with no model in the path. The agent is only
 * asked to rebuild when the panel should be a different *shape*.
 */

import { A2uiSurface, useSurface } from '@travel-a2ui/renderer';

import type { Agent } from '../useAgent.js';
import { Spinner } from './bits.js';

export function Sidebar({ agent }: { agent: Agent }) {
  // Subscribe rather than reading the store during render: the panel arrives
  // from a silent turn, which changes nothing else this component watches.
  const hasSurface = Boolean(useSurface(agent.store, 'sidebar'));

  /*
   * When this panel is *stale* is not the browser's business, and used to be:
   * it watched three trip field names and sent a prose prompt asking for a
   * redraw. The server owns that now — it holds the trip, so it is the only
   * thing that can know the decisions changed shape, and it pushes the new
   * panel down the same turn. All that is left here is the one fact a client
   * genuinely has: this surface is on screen and empty.
   */
  const build = () => agent.drawSurface('sidebar');

  return (
    <aside className="sidebar" aria-label="Trip controls">
      <header className="sidebar__head">
        <h2>The trip</h2>
        {agent.liveSurface === 'sidebar' ? <Spinner /> : null}
      </header>

      {hasSurface ? (
        <div className="sidebar__body">
          {/* The whole panel, and nothing but the panel. What is settled, and
              one way to ask to change each of it — which re-opens the decision
              in the conversation rather than editing it here. */}
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

    </aside>
  );
}
