/**
 * Putting the trip into surfaces, server-side.
 *
 * Every surface reads trip facts from `/trip` in its data model: a control bound
 * to `$/trip/startDate` should open showing the dates already agreed, and the
 * panel should show today's departure airport rather than last turn's.
 *
 * The browser used to do this. `seedTrip` filled a new surface as it arrived and
 * `syncTrip` pushed changes into the standing panels, both by walking a list of
 * travel field names compiled into the client. It worked, and it meant the web
 * app knew what a trip was — so a Swift or Kotlin client would have had to be
 * taught the same list to behave the same way, and taught again every time the
 * trip grew a field.
 *
 * It belongs here instead. The server already holds the trip, already knows
 * which surfaces exist, and can say what it means in the protocol's own words:
 * `dataModel` on the surface it creates, `updateDataModel` for the ones already
 * on screen. Both are messages every A2UI renderer already applies. The client
 * gains nothing to maintain, and loses its copy of the schema.
 */

import { TRIP_KEYS, partyVaries, plan, stops, type Trip } from '@travel-a2ui/trip';
import type { A2uiMessage, Json, JsonObject } from '@travel-a2ui/express';

const VERSION = 'v0.9.1' as const;

/** How a plan step reads on screen. */
const STAGE_LABELS: Record<string, string> = {
  route: 'Where to, and from',
  dates: 'Dates',
  party: 'Who is going',
  flight: 'Flight',
  stay: 'Somewhere to stay',
  budget: 'Budget',
  plan: 'The days',
};

/**
 * The plan, as rows a surface can bind to without computing anything.
 *
 * The panel's checklist used to be a React component reading the trip model
 * directly, which made it the one part of the panel a mobile client could not
 * render. Composing it from catalog components instead needs the agent to draw
 * the *shape* — and then the rows have to arrive as data, or every tick of a
 * checkbox would cost a model turn.
 *
 * So the shape is the agent's and the rows are the server's. Labels, marks and
 * notes are resolved here, which also keeps a Swift client from needing an
 * opinion about what "stay" is called in English.
 */
export function planRows(trip: Trip): JsonObject {
  const state = plan(trip);
  const varies = partyVaries(trip);

  const steps: Json[] = state.steps.map((step) => {
    const isNext = state.next?.stage === step.stage;
    const note = step.skipped
      ? 'not needed'
      : step.pending?.stops.length
        ? step.pending.stops.join(', ')
        : '';
    return {
      stage: step.stage,
      label: STAGE_LABELS[step.stage] ?? step.stage,
      // A glyph rather than a state name: the panel is read, not parsed, and
      // this keeps the binding to one component instead of a conditional.
      mark: step.skipped ? '–' : step.done ? '✓' : isNext ? '→' : '·',
      state: step.skipped ? 'skipped' : step.done ? 'done' : isNext ? 'next' : 'todo',
      note,
      // One string, ready to draw. A template row is a single component and its
      // children cannot be declared inline, so a Row of mark/label/note is not
      // something the agent can express here — and composing it server-side is
      // one less thing for the model to get subtly wrong every turn.
      line: `${step.skipped ? '–' : step.done ? '✓' : isNext ? '→' : '·'} ${
        STAGE_LABELS[step.stage] ?? step.stage
      }${note ? ` — ${note}` : ''}`,
    };
  });

  const route: Json[] = stops(trip).map((leg) => {
    const detail = [
      leg.travelers !== undefined && varies ? `${leg.travelers}×` : '',
      leg.purpose ?? '',
      leg.needsStay === false ? 'no stay needed' : '',
      !leg.startDate ? 'dates?' : '',
      leg.needsStay === true && !leg.selectedHotel ? 'stay?' : '',
    ].filter(Boolean);
    return {
      place: leg.destination,
      detail: detail.join(' · '),
      line: detail.length ? `${leg.destination} — ${detail.join(' · ')}` : leg.destination,
    };
  });

  return {
    done: state.done,
    total: state.total,
    caption: `${state.done} of ${state.total}`,
    complete: state.complete,
    nextLabel: state.next ? (STAGE_LABELS[state.next.stage] ?? state.next.stage) : '',
    steps,
    route,
    // So the panel can decide whether the route is worth drawing at all.
    multiStop: route.length > 1,
  };
}

/** Trip fields worth putting on a surface: set, and not empty. */
function statedFacts(trip: Trip): Array<[string, Json]> {
  const facts: Array<[string, Json]> = [];
  for (const key of TRIP_KEYS) {
    const value = (trip as Record<string, unknown>)[key];
    if (value === undefined || value === null || value === '') continue;
    facts.push([key, value as Json]);
  }
  return facts;
}

/**
 * Fills a newly created surface's `/trip` with what the trip already knows.
 *
 * Only fields the surface left unset. A model that deliberately wrote a value —
 * a suggested date, a widened budget — is *proposing* something, and a proposal
 * should beat the older fact it proposes to replace.
 *
 * This writes into `createSurface.dataModel` rather than following up with
 * `updateDataModel` messages, so the surface is complete in the message that
 * creates it and never paints once empty and again filled. It is also the shape
 * A2UI v1.0 makes standard.
 */
export function seedSurfaceTrip(messages: A2uiMessage[], trip: Trip): A2uiMessage[] {
  const facts = statedFacts(trip);

  // No early return on an empty trip: `/plan` still has to be there, or a panel
  // drawn before anything is decided binds to nothing and renders blank rather
  // than rendering the sequence it is about to walk through.
  for (const message of messages) {
    if (!('createSurface' in message)) continue;

    const model = (message.createSurface.dataModel ?? {}) as JsonObject;
    const existing = (model['trip'] ?? {}) as JsonObject;
    const seeded: JsonObject = { ...existing };

    for (const [key, value] of facts) {
      if (seeded[key] !== undefined) continue;
      seeded[key] = value;
    }

    message.createSurface.dataModel = { ...model, trip: seeded, plan: planRows(trip) };
  }

  return messages;
}

/**
 * `updateDataModel` messages bringing a standing surface up to date.
 *
 * For the panels, which outlive the turn that drew them. An inline card is
 * deliberately not included: it is the record of what was asked at the time, and
 * rewriting history underneath it is worse than letting it be old.
 */
export function tripUpdates(surfaceId: string, trip: Trip): A2uiMessage[] {
  const facts: A2uiMessage[] = statedFacts(trip).map(([key, value]) => ({
    version: VERSION,
    updateDataModel: { surfaceId, path: `/trip/${key}`, value },
  }));

  // The checklist moves whenever the trip does, and it moves without a model
  // turn: the agent drew the shape once and the rows arrive as data.
  facts.push({
    version: VERSION,
    updateDataModel: { surfaceId, path: '/plan', value: planRows(trip) as Json },
  });

  return facts;
}

/** The surfaces that show current state rather than a moment in the past. */
export const STANDING_SURFACES = ['sidebar', 'home'] as const;
