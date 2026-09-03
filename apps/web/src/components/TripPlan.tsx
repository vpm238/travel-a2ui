/**
 * Where the trip has got to, as a checklist.
 *
 * A planner should be visibly planning. The agent knows the sequence — route,
 * dates, party, flight, stay, budget, days — and drives it turn by turn; this
 * is the same sequence made visible, so the traveler can see what is done, what
 * is next, and what does not apply to their trip, without asking.
 *
 * It reads `@travel-a2ui/trip`, the same model the agent's prompt and the tools
 * read, so the panel cannot disagree with what the agent thinks is left.
 */

import { plan, stops, type Trip } from '@travel-a2ui/trip';

const LABELS: Record<string, string> = {
  route: 'Where to, and from',
  dates: 'Dates',
  party: 'Who is going',
  flight: 'Flight',
  stay: 'Somewhere to stay',
  budget: 'Budget',
  plan: 'The days',
};

export function TripPlan({ trip }: { trip: Trip }) {
  const state = plan(trip);
  const legs = stops(trip);
  if (state.done === 0 && !trip.destination) return null;

  return (
    <div className="plan">
      <h3>
        The plan
        <span className="plan__count">
          {state.done}/{state.total}
        </span>
      </h3>

      {legs.length > 1 ? (
        <p className="plan__legs">{legs.map((leg) => leg.destination).join(' → ')}</p>
      ) : null}

      <ol>
        {state.steps.map((step) => {
          const next = state.next?.stage === step.stage;
          return (
            <li
              key={step.stage}
              className={[
                step.done ? 'is-done' : null,
                step.skipped ? 'is-skipped' : null,
                next ? 'is-next' : null,
              ]
                .filter(Boolean)
                .join(' ')}
            >
              <span className="plan__mark" aria-hidden>
                {step.skipped ? '–' : step.done ? '✓' : next ? '→' : '·'}
              </span>
              <span className="plan__label">{LABELS[step.stage] ?? step.stage}</span>
              {step.skipped ? <span className="plan__note">not needed</span> : null}
              {step.incompleteLegs?.length ? (
                <span className="plan__note">{step.incompleteLegs.join(', ')}</span>
              ) : null}
            </li>
          );
        })}
      </ol>

      {state.complete ? <p className="plan__done">Planned. Have a good trip.</p> : null}
    </div>
  );
}
