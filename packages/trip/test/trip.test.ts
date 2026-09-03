/**
 * The trip model, tested where it has to be right.
 *
 * Every case here is a bug that happened, or a shape a real interface actually
 * produced. The model exists because the agent, the tools, the prompt and the
 * browser used to each have their own opinion about these; the point of the
 * tests is that there is now one.
 */

import { describe, expect, it } from 'vitest';

import {
  basisOf,
  canDo,
  coerce,
  merge,
  missingFor,
  nextStepFor,
  nights,
  normalize,
  partyVaries,
  plan,
  problems,
  release,
  stayStatus,
  stops,
  summarize,
  unskip,
  type Trip,
} from '../src/index.js';

describe('getting values in', () => {
  // A ChoicePicker binds a list even when it picks one thing, and the tool
  // downstream expects a string. Left alone this searched for a cabin called
  // "economy," and returned nothing, with no error anywhere.
  it('unwraps a single-item list from a picker', () => {
    expect(coerce('cabin', ['economy'])).toBe('economy');
    expect(normalize({ cabin: ['business'] })).toEqual({ cabin: 'business' });
  });

  it('refuses a choice the catalog does not offer', () => {
    expect(coerce('cabin', 'sleeper')).toBeUndefined();
    expect(coerce('cabin', ['economy', 'business'])).toBeUndefined();
  });

  // A2UI's DateRangePicker binds RFC 3339; `<input type="date">` gives a plain
  // date. Storing both and comparing them later is how a valid range starts
  // looking invalid.
  it('reduces every date shape to one', () => {
    expect(coerce('startDate', '2026-04-12T00:00:00Z')).toBe('2026-04-12');
    expect(coerce('startDate', '2026-04-12')).toBe('2026-04-12');
    expect(coerce('startDate', 'not a date')).toBeUndefined();
  });

  it('reads money the way an interface writes it', () => {
    expect(coerce('budget', '$2,600')).toBe(2600);
    expect(coerce('budget', 2600.4)).toBe(2600);
    expect(coerce('budget', -5)).toBeUndefined();
  });

  it('takes an airport code only when it is one', () => {
    expect(coerce('origin', ' lhr ')).toBe('LHR');
    expect(coerce('origin', 'London')).toBeUndefined();
  });

  it('drops keys that are not part of a trip', () => {
    expect(normalize({ destination: 'Madrid', favouriteColour: 'blue' })).toEqual({
      destination: 'Madrid',
    });
  });

  it('leaves the trip alone when handed nothing useful', () => {
    expect(normalize(undefined)).toEqual({});
    expect(normalize('Madrid')).toEqual({});
    expect(merge({ destination: 'Madrid' }, { destination: '' })).toEqual({ destination: 'Madrid' });
  });
});

describe('what a trip implies', () => {
  const madrid: Trip = { startDate: '2026-04-12', endDate: '2026-04-19' };

  it('counts the nights', () => {
    expect(nights(madrid)).toBe(7);
    expect(nights({ startDate: '2026-04-12' })).toBeUndefined();
    expect(nights({ startDate: '2026-04-19', endDate: '2026-04-12' })).toBeUndefined();
  });

  it('names what a priced surface should say it is priced against', () => {
    expect(basisOf({ ...madrid, origin: 'LHR', destination: 'Madrid', travelers: 3 })).toBe(
      'LHR → Madrid · 12–19 Apr · 3 travellers',
    );
    expect(basisOf({ destination: 'Madrid', travelers: 1 })).toBe('Madrid · 1 traveller');
    expect(basisOf({ destination: 'Madrid', startDate: '2026-04-12' })).toBe('Madrid · from 12 Apr');
    expect(basisOf({})).toBe('');
  });

  it('reports a backwards range rather than storing it', () => {
    const wrong = problems({ startDate: '2026-04-19', endDate: '2026-04-12' });
    expect(wrong).toHaveLength(1);
    expect(wrong[0]!.field).toBe('endDate');
  });

  it('reports a departure that has already gone', () => {
    expect(problems({ startDate: '2026-01-01' }, '2026-09-03')[0]?.field).toBe('startDate');
    expect(problems({ startDate: '2027-01-01' }, '2026-09-03')).toHaveLength(0);
  });

  // Over budget is a real state a dashboard should show, not a rejected write.
  it('flags over-spending without calling it invalid', () => {
    const wrong = problems({ budget: 2000, spent: 2400 });
    expect(wrong[0]?.field).toBe('spent');
  });
});

describe('readiness', () => {
  it('will not price flights without a route and a date', () => {
    expect(missingFor({ destination: 'Madrid' }, 'priceFlights')).toEqual(['origin', 'startDate']);
    expect(canDo({ destination: 'Madrid', origin: 'LHR', startDate: '2026-04-12' }, 'priceFlights')).toBe(
      true,
    );
  });

  it('will not total a trip whose party size it does not know', () => {
    const trip = { destination: 'Madrid', startDate: '2026-04-12', endDate: '2026-04-19' };
    expect(missingFor(trip, 'totalTrip')).toEqual(['travelers']);
  });

  it('summarises what is decided, missing and wrong in one pass', () => {
    const summary = summarize({ destination: 'Madrid', startDate: '2026-04-12' }, '2026-09-03');
    expect(summary.decided.map((entry) => entry.key)).toEqual(['destination', 'startDate']);
    expect(summary.missing).toContain('origin');
    expect(summary.missing).toContain('travelers');
    expect(summary.missing).not.toContain('destination');
  });
});

/**
 * Changing your mind, which is the reason the panel is read-only.
 *
 * Pressing Change releases a decision back into the conversation. The part
 * worth testing is that it takes what depended on it — a flight priced against
 * dates that no longer apply is worse than no flight, because it looks settled.
 */
describe('releasing a decision', () => {
  const booked: Trip = {
    destination: 'Madrid',
    origin: 'LHR',
    startDate: '2026-04-12',
    endDate: '2026-04-19',
    travelers: 2,
    selectedFlight: 'IB614',
    flightPrice: 257,
    selectedHotel: 'h1',
    nightlyPrice: 180,
    budget: 2600,
    planned: true,
  };

  it('takes what was decided because of it', () => {
    const { trip, cleared } = release(booked, ['startDate']);
    expect(cleared).toContain('startDate');
    expect(cleared).toContain('selectedFlight');
    expect(cleared).toContain('selectedHotel');
    expect(trip.selectedFlight).toBeUndefined();
    expect(trip.startDate).toBeUndefined();
    // Not a cascade: the route and the party survive a date change.
    expect(trip.destination).toBe('Madrid');
    expect(trip.travelers).toBe(2);
  });

  it('takes only the fare when the flight itself changes', () => {
    const { trip, cleared } = release(booked, ['selectedFlight']);
    expect(cleared).toEqual(['selectedFlight', 'flightPrice']);
    expect(trip.selectedHotel).toBe('h1');
    expect(trip.startDate).toBe('2026-04-12');
  });

  it('reports nothing when there was nothing to release', () => {
    expect(release({ destination: 'Madrid' }, ['selectedFlight']).cleared).toEqual([]);
  });

  it('reopens the plan at the released step', () => {
    expect(plan(booked).complete).toBe(true);
    expect(plan(release(booked, ['selectedFlight']).trip).next?.stage).toBe('flight');
  });

  // "Actually, we do need a hotel in Madrid" is the same gesture.
  it('puts a ruled-out stage back', () => {
    const skipped: Trip = { destination: 'Brighton', skip: ['stay', 'budget'] };
    expect(unskip(skipped, 'stay').skip).toEqual(['budget']);
    expect(unskip(unskip(skipped, 'stay'), 'budget').skip).toBeUndefined();
  });
});

describe('the plan the agent follows', () => {
  const planned: Trip = {
    destination: 'Madrid',
    origin: 'LHR',
    startDate: '2026-04-12',
    endDate: '2026-04-19',
    travelers: 2,
    selectedFlight: 'IB614',
    selectedHotel: 'h1',
    budget: 2600,
    planned: true,
  };

  it('starts at the beginning and names the next thing', () => {
    const state = plan({});
    expect(state.complete).toBe(false);
    expect(state.next?.stage).toBe('route');
    expect(nextStepFor({})).toMatch(/Step 1 of 7/);
  });

  it('moves on as things get settled', () => {
    const state = plan({ destination: 'Madrid', origin: 'LHR' });
    expect(state.next?.stage).toBe('dates');
    expect(state.done).toBe(1);
  });

  // The point of the whole thing: it has to know when to stop asking.
  it('finishes, and says so', () => {
    const state = plan(planned);
    expect(state.complete).toBe(true);
    expect(state.next).toBeUndefined();
    expect(nextStepFor(planned)).toMatch(/wish them a good trip/);
  });

  it('does not count an unplanned itinerary as planned', () => {
    expect(plan({ ...planned, planned: false }).complete).toBe(false);
  });
});

describe('trips that do not fit the usual shape', () => {
  // Driving to the coast, staying with family, no fixed budget: three stages
  // that a linear planner would keep asking about forever.
  it('treats a ruled-out stage as settled', () => {
    const driving: Trip = {
      destination: 'Brighton',
      origin: 'LHR',
      startDate: '2026-04-12',
      endDate: '2026-04-14',
      travelers: 2,
      planned: true,
      skip: ['flight', 'stay', 'budget'],
    };
    const state = plan(driving);
    expect(state.complete).toBe(true);
    expect(state.steps.filter((step) => step.skipped).map((step) => step.stage)).toEqual([
      'flight',
      'stay',
      'budget',
    ]);
  });

  it('only skips stages that exist', () => {
    expect(coerce('skip', ['flight', 'teleportation'])).toEqual(['flight']);
    expect(coerce('skip', [])).toBeUndefined();
  });

  it('carries more than one stop', () => {
    const twoCity: Trip = {
      destination: 'Lisbon',
      origin: 'LHR',
      startDate: '2026-04-12',
      endDate: '2026-04-15',
      legs: [{ destination: 'Madrid', startDate: '2026-04-15', endDate: '2026-04-19' }],
    };
    expect(stops(twoCity).map((leg) => leg.destination)).toEqual(['Lisbon', 'Madrid']);
  });

  // The failure this prevents: dates look settled because the *first* city has
  // them, and the second city is quietly never asked about.
  it('does not call the dates settled while a later stop has none', () => {
    const trip: Trip = {
      destination: 'Lisbon',
      origin: 'LHR',
      startDate: '2026-04-12',
      endDate: '2026-04-15',
      legs: [{ destination: 'Madrid' }],
    };
    const step = plan(trip).next;
    expect(step?.stage).toBe('dates');
    expect(step?.pending).toEqual({ stops: ['Madrid'], want: 'dates' });
    expect(nextStepFor(trip)).toContain('Madrid');
  });

  /**
   * The trip that broke the model, kept as the case to hold it honest.
   *
   * "SFO to New York with a stop in Chicago for two nights for a wedding, then
   * back to SFO — but two tickets coming home, because I'm travelling back with
   * a friend." One trip, three legs, two party sizes, and a return that is not
   * a mirror of the outbound.
   */
  const wedding: Trip = {
    destination: 'Chicago',
    origin: 'SFO',
    startDate: '2026-10-09',
    endDate: '2026-10-11',
    travelers: 1,
    legs: [
      { destination: 'New York', startDate: '2026-10-11', endDate: '2026-10-15', purpose: 'the wedding' },
      { destination: 'San Francisco', startDate: '2026-10-15', endDate: '2026-10-15', travelers: 2 },
    ],
  };

  it('holds a route with a stopover and a return', () => {
    expect(stops(wedding).map((leg) => `${leg.origin}→${leg.destination}`)).toEqual([
      'SFO→Chicago',
      'Chicago→New York',
      'New York→San Francisco',
    ]);
  });

  // Without this the return is priced for one person and the friend has no seat.
  it('carries a different party size on the leg that has one', () => {
    expect(stops(wedding).map((leg) => leg.travelers)).toEqual([1, 1, 2]);
    expect(partyVaries(wedding)).toBe(true);
    expect(partyVaries({ ...wedding, legs: [] })).toBe(false);
  });

  it('keeps why a stop exists', () => {
    expect(stops(wedding)[1]?.purpose).toBe('the wedding');
  });

  it('coerces a leg party size the way it coerces everything else', () => {
    expect(coerce('legs', [{ destination: 'NYC', travelers: '2' }])).toEqual([
      { destination: 'NYC', travelers: 2 },
    ]);
  });

  /**
   * Three cities does not mean three hotels. This is the question that has to
   * be asked per stop, and answered per stop, or the agent nags about a city
   * where someone is staying with family.
   */
  describe('somewhere to stay, stop by stop', () => {
    const route: Trip = {
      destination: 'Lisbon',
      origin: 'LHR',
      startDate: '2026-04-12',
      endDate: '2026-04-15',
      travelers: 2,
      selectedFlight: 'TP1',
      legs: [{ destination: 'Madrid', startDate: '2026-04-15', endDate: '2026-04-19' }],
    };

    it('asks about every stop before it asks about a hotel', () => {
      const step = plan(route).next;
      expect(step?.stage).toBe('stay');
      expect(step?.pending?.stops).toEqual(['Lisbon', 'Madrid']);
      expect(step?.pending?.want).toMatch(/whether a stay is needed/);
    });

    it('stops asking about a stop that does not need one', () => {
      const withSister: Trip = {
        ...route,
        legs: [{ ...route.legs![0]!, needsStay: true }],
        // The flat fields are Lisbon; a leg-level answer lives on the leg.
      };
      const status = stayStatus({
        ...withSister,
        legs: [{ destination: 'Lisbon', needsStay: false }, ...withSister.legs!.slice(0)],
      });
      expect(status.notNeeded).toContain('Lisbon');
      expect(status.needed).toContain('Madrid');
    });

    it('is finished once every stop is answered', () => {
      const settled: Trip = {
        ...route,
        selectedHotel: 'h_lisbon',
        legs: [{ ...route.legs![0]!, needsStay: false }],
      };
      const stayStep = plan(settled).steps.find((step) => step.stage === 'stay');
      expect(stayStep?.done).toBe(true);
      expect(stayStatus(settled).booked).toEqual(['Lisbon']);
      expect(stayStatus(settled).notNeeded).toEqual(['Madrid']);
    });

    it('offers what is actually left once the trip is planned', () => {
      const done: Trip = {
        ...route,
        selectedHotel: 'h_lisbon',
        budget: 2600,
        planned: true,
        legs: [{ ...route.legs![0]!, needsStay: false }],
      };
      expect(plan(done).complete).toBe(true);
      const closing = nextStepFor(done);
      expect(closing).toMatch(/adding more to the days/);
      expect(closing).toMatch(/sharing the plan/);
      expect(closing).toMatch(/good trip/);
    });
  });

  it('ignores a leg that names no place', () => {
    expect(coerce('legs', [{ startDate: '2026-04-12' }])).toBeUndefined();
    expect(coerce('legs', [{ destination: 'Madrid', startDate: 'nonsense' }])).toEqual([
      { destination: 'Madrid' },
    ]);
  });
});
