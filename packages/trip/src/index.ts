/**
 * The trip: what planning one actually requires, as a model.
 *
 * This started as a loose bag of keys that the agent, the tools, the prompt and
 * the browser each interpreted slightly differently — and every bug worth
 * reporting came out of that gap. Dates existed in two formats. `cabin` arrived
 * from a picker as `["economy"]` and reached a tool expecting `"economy"`.
 * Whether a trip had enough information to be priced was decided independently,
 * and differently, in three places. Two copies of the field list drifted.
 *
 * So there is one definition, here, and everything reads it:
 *
 *   - **`FIELDS`** is the schema. What a trip is made of, how each part is
 *     spelled, and which of them a given job needs before it can start.
 *   - **`normalize`** is the only way values get in. It coerces the shapes a
 *     real interface produces — a picker's single-item array, an RFC 3339
 *     instant from a date input, a number typed as a string.
 *   - **`missingFor`** answers "can this be priced yet", once, for everyone.
 *   - **`bindingFor`** gives the `$/trip/…` path a control binds to, so the
 *     surface, the host and the server agree on where a value lives.
 *
 * This package has no dependencies and no I/O on purpose: it is shared by a
 * Cloudflare Worker, a browser bundle and a test suite, and it is small enough
 * to read in one sitting.
 */

/** What a field holds, which decides how a loose value is coerced into it. */
export type FieldKind =
  | 'text'
  | 'code'
  | 'date'
  | 'count'
  | 'money'
  | 'flag'
  | 'choice'
  | 'stages'
  | 'legs';

/** The stages of planning a trip, in the order they get decided. */
export type Stage = 'route' | 'dates' | 'party' | 'flight' | 'stay' | 'budget' | 'plan';

export interface Field {
  key: string;
  kind: FieldKind;
  /** How to refer to it when asking a person for it. */
  label: string;
  stage: Stage;
  /** Allowed values, for a choice. */
  options?: readonly string[];
  /** One line on what it is for, used in generated documentation. */
  note: string;
}

/**
 * Everything a trip is made of.
 *
 * Deliberately flat. A nested model reads better in a type and is worse in
 * practice here, because these values are bound into a UI one at a time
 * (`$/trip/startDate`), sent back one at a time, and named one at a time when
 * the agent asks for what is missing. Nesting would buy tidiness in the one
 * place it is never needed and cost clarity everywhere it is.
 */
export const FIELDS = [
  {
    key: 'destination',
    kind: 'text',
    label: 'where you are going',
    stage: 'route',
    note: 'City or airport. Everything else is priced against it.',
  },
  {
    key: 'origin',
    kind: 'code',
    label: 'which airport you are flying from',
    stage: 'route',
    note: 'Three-letter code. Never assumed — suggested from the browser, confirmed by the traveler.',
  },
  {
    key: 'startDate',
    kind: 'date',
    label: 'when you are leaving',
    stage: 'dates',
    note: 'YYYY-MM-DD. No fare is real without it.',
  },
  {
    key: 'endDate',
    kind: 'date',
    label: 'when you are coming back',
    stage: 'dates',
    note: 'YYYY-MM-DD. With startDate it gives the number of nights.',
  },
  {
    key: 'travelers',
    kind: 'count',
    label: 'how many of you are going',
    stage: 'party',
    note: 'Adults and older children — everyone needing a seat and a bed.',
  },
  {
    key: 'cabin',
    kind: 'choice',
    label: 'which cabin',
    stage: 'flight',
    options: ['economy', 'premium', 'business', 'first'],
    note: 'Defaults to economy when nobody says otherwise.',
  },
  {
    key: 'nonstopOnly',
    kind: 'flag',
    label: 'whether to exclude connections',
    stage: 'flight',
    note: 'A preference, not a requirement: it filters the search.',
  },
  {
    key: 'maxFare',
    kind: 'money',
    label: 'the most you would pay per seat',
    stage: 'flight',
    note: 'Per traveler, one way. Filters the search rather than the display.',
  },
  {
    key: 'selectedFlight',
    kind: 'text',
    label: 'the flight you chose',
    stage: 'flight',
    note: 'The id from the card they tapped. Its fare feeds the total.',
  },
  {
    key: 'flightPrice',
    kind: 'money',
    label: 'what that flight costs',
    stage: 'flight',
    note: 'Per traveler. Saved alongside the id so the total is theirs, not an average.',
  },
  {
    key: 'neighborhood',
    kind: 'text',
    label: 'which part of town',
    stage: 'stay',
    note: 'Narrows the stays that come back.',
  },
  {
    key: 'maxNightly',
    kind: 'money',
    label: 'the most per night',
    stage: 'stay',
    note: 'Filters stays. Distinct from the trip budget.',
  },
  {
    key: 'selectedHotel',
    kind: 'text',
    label: 'where you are staying',
    stage: 'stay',
    note: 'The id from the card they tapped.',
  },
  {
    key: 'nightlyPrice',
    kind: 'money',
    label: 'what that stay costs a night',
    stage: 'stay',
    note: 'Saved with the id, for the same reason as flightPrice.',
  },
  {
    key: 'budget',
    kind: 'money',
    label: 'what the whole trip should come to',
    stage: 'budget',
    note: 'All in, for everyone. What the progress meter measures against.',
  },
  {
    key: 'spent',
    kind: 'money',
    label: 'what is committed so far',
    stage: 'budget',
    note: 'Booked, not estimated.',
  },
  {
    key: 'notes',
    kind: 'text',
    label: 'anything else worth remembering',
    stage: 'budget',
    note: 'One line. Preferences and constraints that do not have a field.',
  },
  {
    key: 'planned',
    kind: 'flag',
    label: 'a day-by-day plan',
    stage: 'plan',
    note: 'Set once the itinerary has been drawn and the traveler is happy with it.',
  },
  {
    key: 'skip',
    kind: 'stages',
    label: 'the parts that do not apply',
    stage: 'route',
    note:
      "Stages this trip does not need — driving rather than flying, staying with family, " +
      'no fixed budget. A skipped stage counts as settled and is never asked about again.',
  },
  {
    key: 'legs',
    kind: 'legs',
    label: 'the other stops',
    stage: 'route',
    note:
      'Additional stops beyond the first, each with its own dates. The flat fields describe ' +
      'the first leg; this is how a two-city trip stops being two half-described trips.',
  },
] as const satisfies readonly Field[];

export type TripKey = (typeof FIELDS)[number]['key'];

export type Trip = Partial<{
  destination: string;
  origin: string;
  startDate: string;
  endDate: string;
  travelers: number;
  cabin: string;
  nonstopOnly: boolean;
  maxFare: number;
  selectedFlight: string;
  flightPrice: number;
  neighborhood: string;
  maxNightly: number;
  selectedHotel: string;
  nightlyPrice: number;
  budget: number;
  spent: number;
  notes: string;
  planned: boolean;
  /** Stages this particular trip does not need. */
  skip: Stage[];
  /** Stops after the first. The flat fields above are leg one. */
  legs: Leg[];
}>;

/**
 * One stop on a trip that has more than one.
 *
 * A leg is a place, a span, and — where it differs from the rest of the trip —
 * who is on it and why. That last part is not decoration: "SFO to New York via
 * Chicago for a wedding, coming back with two of us" is one trip with three
 * legs and two different party sizes, and a model with a single `travelers`
 * silently prices the return for the wrong number of people.
 *
 * Money stays trip-level. People say "about $2,000 all in", not "$900 for the
 * Chicago portion", and splitting the budget per leg would model an accounting
 * exercise nobody asked for.
 */
export interface Leg {
  destination: string;
  startDate?: string;
  endDate?: string;
  /** Where this leg departs from, when it is not the previous stop. */
  origin?: string;
  /** Only when it differs from the trip's party size. */
  travelers?: number;
  /** Why this stop exists — 'the wedding', 'work'. Shapes what gets planned. */
  purpose?: string;
  /**
   * Whether this stop needs somewhere to stay.
   *
   * Undefined means nobody has asked yet, and that is the point: a trip through
   * three cities does not need three hotels, and the difference — a friend's
   * spare room, a wedding block, a red-eye out the same night — is a question
   * per stop, not one for the trip. `false` settles the stop without a booking;
   * `true` means it is still waiting on one.
   */
  needsStay?: boolean;
  /** The stay chosen for this stop. */
  selectedHotel?: string;
  nightlyPrice?: number;
  notes?: string;
}

const BY_KEY = new Map<string, Field>(FIELDS.map((field) => [field.key, field]));

export const TRIP_KEYS: readonly TripKey[] = FIELDS.map((field) => field.key);

export function isTripKey(key: string): key is TripKey {
  return BY_KEY.has(key);
}

export function fieldFor(key: string): Field | undefined {
  return BY_KEY.get(key);
}

/** The data-model path a control binds to. One spelling, everywhere. */
export function bindingFor(key: TripKey): string {
  return `/trip/${key}`;
}

// ---------------------------------------------------------------- coercion

const isBlank = (value: unknown): boolean =>
  value === undefined || value === null || value === '';

/**
 * A date as `YYYY-MM-DD`, from any of the shapes an interface produces.
 *
 * `<input type="date">` gives a plain date, A2UI's DateRangePicker binds an
 * RFC 3339 instant, and a model writing JSON will produce either. Storing both
 * and comparing them later is how a range ends up looking invalid when it is
 * not.
 */
function toDate(value: unknown): string | undefined {
  if (typeof value === 'number') return new Date(value).toISOString().slice(0, 10);
  if (typeof value !== 'string' || !value.trim()) return undefined;
  const trimmed = value.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return trimmed;
  const parsed = new Date(trimmed);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString().slice(0, 10);
}

function toNumber(value: unknown): number | undefined {
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
  if (typeof value !== 'string') return undefined;
  // Money arrives from an interface as "$1,240" as often as 1240.
  const cleaned = value.replace(/[^0-9.-]/g, '');
  const parsed = Number.parseFloat(cleaned);
  return Number.isFinite(parsed) ? parsed : undefined;
}

/** Every stage, in order. The one list the plan and the skips both read. */
export const STAGES: readonly Stage[] = [
  'route',
  'dates',
  'party',
  'flight',
  'stay',
  'budget',
  'plan',
];

/** A leg from whatever shape it arrived in, or nothing if it names no place. */
function toLeg(value: unknown): Leg | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  const raw = value as Record<string, unknown>;
  const destination = typeof raw['destination'] === 'string' ? raw['destination'].trim() : '';
  if (!destination) return undefined;

  const start = toDate(raw['startDate']);
  const end = toDate(raw['endDate']);
  const origin =
    typeof raw['origin'] === 'string' && /^[A-Za-z]{3}$/.test(raw['origin'].trim())
      ? raw['origin'].trim().toUpperCase()
      : undefined;
  const text = (key: string) =>
    typeof raw[key] === 'string' && (raw[key] as string).trim()
      ? (raw[key] as string).trim().slice(0, 200)
      : undefined;

  const party = toNumber(raw['travelers']);
  const travelers = party === undefined ? undefined : Math.max(1, Math.round(party));
  const needsStay = toFlag(raw['needsStay']);
  const nightly = toNumber(raw['nightlyPrice']);

  return {
    destination: destination.slice(0, 120),
    ...(start ? { startDate: start } : {}),
    ...(end ? { endDate: end } : {}),
    ...(origin ? { origin } : {}),
    ...(travelers === undefined ? {} : { travelers }),
    ...(needsStay === undefined ? {} : { needsStay }),
    ...(text('selectedHotel') ? { selectedHotel: text('selectedHotel') } : {}),
    ...(nightly === undefined ? {} : { nightlyPrice: Math.round(nightly) }),
    ...(text('purpose') ? { purpose: text('purpose') } : {}),
    ...(text('notes') ? { notes: text('notes') } : {}),
  };
}

function toFlag(value: unknown): boolean | undefined {
  if (typeof value === 'boolean') return value;
  if (value === 'true' || value === 'yes' || value === 1) return true;
  if (value === 'false' || value === 'no' || value === 0) return false;
  return undefined;
}

/**
 * Coerces one loose value into the field's shape, or rejects it.
 *
 * A multi-select bound to a single-valued field is the case worth naming: a
 * ChoicePicker hands back `["economy"]`, and a tool that expects a string then
 * searches for a cabin called `economy,` — no error, wrong answer.
 */
export function coerce(key: string, value: unknown): unknown {
  const field = BY_KEY.get(key);
  if (!field || isBlank(value)) return undefined;

  if (Array.isArray(value) && field.kind !== 'stages' && field.kind !== 'legs') {
    return value.length === 1 ? coerce(key, value[0]) : undefined;
  }

  switch (field.kind) {
    case 'stages': {
      const wanted = (Array.isArray(value) ? value : [value])
        .map((entry) => String(entry).trim().toLowerCase())
        .filter((entry): entry is Stage => (STAGES as readonly string[]).includes(entry));
      return wanted.length > 0 ? [...new Set(wanted)] : undefined;
    }
    case 'legs': {
      const legs = (Array.isArray(value) ? value : [value])
        .map(toLeg)
        .filter((leg): leg is Leg => leg !== undefined);
      return legs.length > 0 ? legs : undefined;
    }
    case 'date':
      return toDate(value);
    case 'count': {
      const count = toNumber(value);
      return count === undefined ? undefined : Math.max(0, Math.round(count));
    }
    case 'money': {
      const amount = toNumber(value);
      return amount === undefined || amount < 0 ? undefined : Math.round(amount);
    }
    case 'flag':
      return toFlag(value);
    case 'code': {
      const code = String(value).trim().toUpperCase();
      return /^[A-Z]{3}$/.test(code) ? code : undefined;
    }
    case 'choice': {
      const choice = String(value).trim().toLowerCase();
      return field.options?.includes(choice) ? choice : undefined;
    }
    default: {
      const text = String(value).trim();
      return text ? text.slice(0, 400) : undefined;
    }
  }
}

/** Everything in `value` that belongs to a trip, in the shape a trip wants. */
export function normalize(value: unknown): Trip {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const out: Record<string, unknown> = {};
  for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
    const coerced = coerce(key, raw);
    if (coerced !== undefined) out[key] = coerced;
  }
  return out as Trip;
}

/** A patch applied to a trip, with the patch normalised first. */
export function merge(trip: Trip, patch: unknown): Trip {
  return { ...trip, ...normalize(patch) };
}

/**
 * What else has to be let go when one decision is released.
 *
 * Changing the dates does not just change the dates: the flight was priced
 * against them and the stay was booked for those nights, and leaving either in
 * place means the panel keeps showing a decision that is no longer true. So
 * releasing a value releases what was decided *because* of it.
 *
 * Deliberately shallow — one level, and only where the dependency is real.
 * Cascading further would clear a trip someone spent an hour on because they
 * moved a date by a day.
 */
const DEPENDENTS: Partial<Record<TripKey, readonly TripKey[]>> = {
  destination: ['selectedFlight', 'flightPrice', 'selectedHotel', 'nightlyPrice', 'neighborhood', 'planned'],
  origin: ['selectedFlight', 'flightPrice'],
  startDate: ['selectedFlight', 'flightPrice', 'selectedHotel', 'nightlyPrice', 'planned'],
  endDate: ['selectedHotel', 'nightlyPrice', 'planned'],
  travelers: ['selectedFlight', 'flightPrice', 'selectedHotel', 'nightlyPrice'],
  selectedFlight: ['flightPrice'],
  selectedHotel: ['nightlyPrice'],
};

/** The fields a release clears: the one named, plus what depended on it. */
export function released(keys: readonly TripKey[]): TripKey[] {
  const out = new Set<TripKey>();
  for (const key of keys) {
    out.add(key);
    for (const dependent of DEPENDENTS[key] ?? []) out.add(dependent);
  }
  return [...out];
}

/**
 * Lets go of a decision so it can be made again.
 *
 * The panel is read-only; changing something means releasing it back into the
 * conversation, where it is re-asked pre-filled. Clearing it here is what stops
 * the rest of the app pricing against a choice the traveler has withdrawn — and
 * clearing a skipped stage un-skips it, because "actually we do need a hotel"
 * is the same gesture.
 */
export function release(trip: Trip, keys: readonly TripKey[]): { trip: Trip; cleared: TripKey[] } {
  const cleared = released(keys).filter((key) => trip[key as keyof Trip] !== undefined);
  const next: Record<string, unknown> = { ...trip };
  for (const key of cleared) delete next[key];
  return { trip: next as Trip, cleared };
}

/** Puts a ruled-out stage back into the plan. */
export function unskip(trip: Trip, stage: Stage): Trip {
  const remaining = (trip.skip ?? []).filter((entry) => entry !== stage);
  const next: Record<string, unknown> = { ...trip };
  if (remaining.length > 0) next['skip'] = remaining;
  else delete next['skip'];
  return next as Trip;
}

// ---------------------------------------------------------------- derived

/** Nights implied by the range, if there is a coherent one. */
export function nights(trip: Trip): number | undefined {
  if (!trip.startDate || !trip.endDate) return undefined;
  const span = Math.round(
    (Date.parse(`${trip.endDate}T00:00:00Z`) - Date.parse(`${trip.startDate}T00:00:00Z`)) /
      86_400_000,
  );
  return Number.isFinite(span) && span > 0 ? span : undefined;
}

/** Days until departure, from a given day. Negative means it has gone. */
export function daysUntil(trip: Trip, today: string): number | undefined {
  if (!trip.startDate) return undefined;
  const span = Math.round(
    (Date.parse(`${trip.startDate}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000,
  );
  return Number.isFinite(span) ? span : undefined;
}

export interface Problem {
  field: TripKey;
  message: string;
}

/**
 * What is wrong with a trip as saved, as opposed to merely unfinished.
 *
 * Only things that would make a downstream number a lie. Somewhere to stay
 * being undecided is fine; a return before the departure is not, because
 * everything from nights to the total is computed off that range.
 */
export function problems(trip: Trip, today?: string): Problem[] {
  const found: Problem[] = [];

  if (trip.startDate && trip.endDate && nights(trip) === undefined) {
    found.push({
      field: 'endDate',
      message: `${trip.endDate} is not after ${trip.startDate}.`,
    });
  }
  if (today && trip.startDate) {
    const until = daysUntil(trip, today);
    if (until !== undefined && until < 0) {
      found.push({ field: 'startDate', message: `${trip.startDate} is in the past.` });
    }
  }
  if (trip.travelers !== undefined && trip.travelers < 1) {
    found.push({ field: 'travelers', message: 'A trip needs at least one traveler.' });
  }
  if (trip.budget !== undefined && trip.spent !== undefined && trip.spent > trip.budget) {
    // Not an error — a real state a dashboard should show — so it is reported
    // rather than rejected.
    found.push({ field: 'spent', message: 'Committed spend is over the budget.' });
  }

  return found;
}

// ------------------------------------------------------------- readiness

/** A thing the agent might try to do, and what it cannot do without. */
export const REQUIREMENTS = {
  priceFlights: ['destination', 'origin', 'startDate'],
  priceStay: ['destination', 'startDate', 'endDate'],
  totalTrip: ['destination', 'startDate', 'endDate', 'travelers'],
  planDays: ['destination', 'startDate', 'endDate'],
} as const satisfies Record<string, readonly TripKey[]>;

export type Goal = keyof typeof REQUIREMENTS;

/**
 * The fields a goal needs and does not have.
 *
 * One answer to "can this be priced yet", instead of the three slightly
 * different answers the tools, the prompt and the UI used to reach on their own.
 */
export function missingFor(trip: Trip, goal: Goal): TripKey[] {
  return REQUIREMENTS[goal].filter((key) => isBlank(trip[key as keyof Trip]));
}

export function canDo(trip: Trip, goal: Goal): boolean {
  return missingFor(trip, goal).length === 0;
}

/** The missing fields as a sentence to put in front of a person. */
export function askFor(keys: readonly TripKey[]): string {
  const labels = keys.map((key) => BY_KEY.get(key)?.label ?? key);
  if (labels.length === 0) return '';
  if (labels.length === 1) return labels[0]!;
  return `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`;
}

// --------------------------------------------------------------- reporting

export interface Summary {
  decided: Array<{ key: TripKey; value: unknown; label: string }>;
  missing: TripKey[];
  nights?: number;
  problems: Problem[];
}

/** The trip as the app and the prompt both want to show it. */
export function summarize(trip: Trip, today?: string): Summary {
  const decided: Summary['decided'] = [];
  for (const field of FIELDS) {
    const value = trip[field.key as keyof Trip];
    if (!isBlank(value)) decided.push({ key: field.key, value, label: field.label });
  }

  const nightCount = nights(trip);
  return {
    decided,
    // Only the fields that block something. `notes` being empty is not news.
    missing: [...new Set(Object.keys(REQUIREMENTS).flatMap((goal) => missingFor(trip, goal as Goal)))],
    ...(nightCount === undefined ? {} : { nights: nightCount }),
    problems: problems(trip, today),
  };
}

/**
 * How a surface should describe what it is showing.
 *
 * `LHR → Madrid · 12–19 Apr · 3 travellers`. A fare with no route, dates or
 * party size beside it is the thing that makes an answer untrustworthy, and
 * every priced surface is asked to carry this.
 */
export function basisOf(trip: Trip): string {
  const parts: string[] = [];

  if (trip.origin && trip.destination) parts.push(`${trip.origin} → ${trip.destination}`);
  else if (trip.destination) parts.push(trip.destination);

  const short = (date: string) =>
    new Date(`${date}T00:00:00Z`).toLocaleDateString('en-GB', {
      day: 'numeric',
      month: 'short',
      timeZone: 'UTC',
    });

  if (trip.startDate && trip.endDate) {
    const from = short(trip.startDate);
    const to = short(trip.endDate);
    // Same month reads better as "12–19 Apr" than "12 Apr – 19 Apr".
    const sameMonth = trip.startDate.slice(0, 7) === trip.endDate.slice(0, 7);
    parts.push(sameMonth ? `${from.split(' ')[0]}–${to}` : `${from} – ${to}`);
  } else if (trip.startDate) {
    // A one-way or half-decided trip still says when it leaves, in the same
    // voice as the rest — a raw ISO date in a heading reads like a database.
    parts.push(`from ${short(trip.startDate)}`);
  }

  if (trip.travelers !== undefined) {
    parts.push(`${trip.travelers} traveller${trip.travelers === 1 ? '' : 's'}`);
  }

  return parts.join(' · ');
}

// -------------------------------------------------------------------- plan

/**
 * The trip as a sequence of steps, so the agent can lead rather than wait.
 *
 * A planner that answers questions is a search box with better manners. What
 * makes it a planner is knowing what has to happen next and saying so — and
 * knowing when there is nothing left, so it can stop asking and wish you a good
 * trip instead of inventing another question.
 *
 * The order is the order these actually get decided: you cannot price a flight
 * before you know the route and the dates, and there is no point discussing
 * neighbourhoods before there is a city.
 */
export interface Step {
  stage: Stage;
  /** What this step is, phrased as the thing to do next. */
  label: string;
  /** Fields that must be filled for the step to be done. */
  needs: readonly TripKey[];
  /** Which of them are still missing. */
  missing: TripKey[];
  done: boolean;
  /** True when the traveler ruled this stage out rather than completing it. */
  skipped: boolean;
  /**
   * Stops this stage is still waiting on, and what it is waiting for.
   *
   * Some stages are per-stop rather than per-trip. A trip through Lisbon and
   * Madrid has two places that each need a span, and somewhere to stay is a
   * question *per city* — three cities do not mean three hotels, because one of
   * them might be a friend's spare room. Reporting the stops here is what stops
   * the agent declaring a stage settled because the first leg is.
   */
  pending?: { stops: string[]; want: string };
}

const STEPS: ReadonlyArray<{ stage: Stage; label: string; needs: readonly TripKey[] }> = [
  { stage: 'route', label: 'settle where they are going and flying from', needs: ['destination', 'origin'] },
  { stage: 'dates', label: 'settle the dates', needs: ['startDate', 'endDate'] },
  { stage: 'party', label: 'settle how many are travelling', needs: ['travelers'] },
  { stage: 'flight', label: 'choose a flight', needs: ['selectedFlight'] },
  // No trip-level field: whether a stay is needed, and which one, is decided
  // per stop. `pendingFor` is what makes this step complete.
  { stage: 'stay', label: 'sort out where you are sleeping, stop by stop', needs: [] },
  { stage: 'budget', label: 'agree what the trip should cost', needs: ['budget'] },
  { stage: 'plan', label: 'plan the days', needs: ['planned'] },
];

export interface Plan {
  steps: Step[];
  /** The first unfinished step, or undefined when the trip is planned. */
  next?: Step;
  /** Steps finished or ruled out, of all of them. */
  done: number;
  total: number;
  complete: boolean;
}

/**
 * Stops in order, each resolved against the trip and the stop before it.
 *
 * Two defaults are filled in here so nothing downstream has to reimplement
 * them: a leg with no origin departs from wherever the previous leg ended, and
 * a leg with no party size carries the trip's. Both are what a person means
 * when they leave it out.
 */
export function stops(trip: Trip): Leg[] {
  const first: Leg | undefined = trip.destination
    ? {
        destination: trip.destination,
        ...(trip.origin ? { origin: trip.origin } : {}),
        ...(trip.startDate ? { startDate: trip.startDate } : {}),
        ...(trip.endDate ? { endDate: trip.endDate } : {}),
        ...(trip.travelers === undefined ? {} : { travelers: trip.travelers }),
      }
    : undefined;

  const all = [...(first ? [first] : []), ...(trip.legs ?? [])];

  return all.map((leg, index) => ({
    ...leg,
    origin: leg.origin ?? (index > 0 ? all[index - 1]!.destination : trip.origin),
    travelers: leg.travelers ?? trip.travelers,
    // The trip's own hotel choice belongs to the first stop, which is what the
    // flat fields describe.
    ...(index === 0 && leg.selectedHotel === undefined && trip.selectedHotel
      ? { selectedHotel: trip.selectedHotel }
      : {}),
  }));
}

/** Stops grouped by where the question of somewhere to stay has got to. */
export function stayStatus(trip: Trip): {
  unasked: string[];
  needed: string[];
  booked: string[];
  notNeeded: string[];
} {
  const unasked: string[] = [];
  const needed: string[] = [];
  const booked: string[] = [];
  const notNeeded: string[] = [];

  for (const leg of stops(trip)) {
    // A stay already chosen answers the question, whether or not anyone asked.
    if (leg.selectedHotel) booked.push(leg.destination);
    else if (leg.needsStay === false) notNeeded.push(leg.destination);
    else if (leg.needsStay === true) needed.push(leg.destination);
    else unasked.push(leg.destination);
  }

  return { unasked, needed, booked, notNeeded };
}

/** True when the legs do not all carry the same number of people. */
export function partyVaries(trip: Trip): boolean {
  const counts = stops(trip)
    .map((leg) => leg.travelers)
    .filter((count): count is number => count !== undefined);
  return new Set(counts).size > 1;
}

/**
 * The trip as steps, bending around what this particular trip does not need.
 *
 * Two things keep it from being a march. A stage in `skip` is settled by having
 * been ruled out — someone driving is not asked to choose a flight, and someone
 * staying with family is not asked to choose a hotel. And the route and date
 * stages are evaluated per stop, so a two-city trip is not declared dated
 * because the first city has dates.
 */
/**
 * What a per-stop stage is still waiting on, if anything.
 *
 * Only two stages are per-stop. Dates, because every place needs a span. And
 * somewhere to stay, because that is a question you ask city by city — and the
 * answer "not there, I'm at my sister's" has to be recordable, or the agent
 * asks about it forever.
 */
function pendingFor(
  trip: Trip,
  stage: Stage,
  legs: Leg[],
): { stops: string[]; want: string } | undefined {
  if (stage === 'dates') {
    const undated = legs.filter((leg) => !leg.startDate || !leg.endDate).map((l) => l.destination);
    return undated.length > 0 ? { stops: undated, want: 'dates' } : undefined;
  }

  if (stage === 'stay') {
    // A per-stop stage cannot be settled before there are stops. Without this
    // an empty trip counts "somewhere to stay" as done, and the plan opens at
    // step two of a trip nobody has started.
    if (legs.length === 0) return { stops: [], want: 'a destination first' };

    const status = stayStatus(trip);
    if (status.unasked.length > 0) {
      return { stops: status.unasked, want: 'to know whether a stay is needed' };
    }
    if (status.needed.length > 0) return { stops: status.needed, want: 'somewhere to stay' };
  }

  return undefined;
}

export function plan(trip: Trip): Plan {
  const skipped = new Set(trip.skip ?? []);
  const legs = stops(trip);

  const steps: Step[] = STEPS.map((step) => {
    if (skipped.has(step.stage)) {
      return { ...step, missing: [], done: true, skipped: true };
    }

    const missing = step.needs.filter((key) => {
      const value = trip[key as keyof Trip];
      // A flag is only satisfied when it is actually true: `planned: false`
      // means the days are still unplanned, not that the question was answered.
      return isBlank(value) || (BY_KEY.get(key)?.kind === 'flag' && value !== true);
    });

    const pending = pendingFor(trip, step.stage, legs);

    return {
      ...step,
      missing,
      ...(pending ? { pending } : {}),
      done: missing.length === 0 && !pending,
      skipped: false,
    };
  });

  const next = steps.find((step) => !step.done);
  const done = steps.filter((step) => step.done).length;

  return {
    steps,
    ...(next ? { next } : {}),
    done,
    total: steps.length,
    complete: next === undefined,
  };
}

/**
 * What the agent should be doing on this turn, in one line.
 *
 * Deliberately imperative, because it is dropped straight into the prompt and
 * the job it has to do there is stop the agent from stalling politely.
 */
export function nextStepFor(trip: Trip): string {
  const state = plan(trip);
  const legs = stops(trip);

  if (state.complete) {
    return (
      `The trip is planned — every stage is settled or ruled out${
        legs.length > 1 ? `, across all ${legs.length} stops` : ''
      }. Do not invent another question about it. Show them the whole trip on one surface, ` +
      'offer the two things that are actually left — adding more to the days, or sharing the ' +
      'plan with whoever else is coming — and wish them a good trip.'
    );
  }

  const step = state.next!;
  const parts = [`Step ${state.done + 1} of ${state.total}: ${step.label}.`];

  if (step.pending && step.pending.stops.length > 0) {
    parts.push(
      `Waiting on ${step.pending.stops.join(', ')} — ${step.pending.want}. ` +
        (step.stage === 'stay'
          ? 'Ask per stop, in one surface: which of these need somewhere to stay and which do ' +
            'not. Record a stop that does not with needsStay: false on its leg, and stop ' +
            'asking about it.'
          : 'A trip with several stops needs one for each, not one covering all of them.'),
    );
  }
  if (step.missing.length > 0) {
    parts.push(
      `You still need ${askFor(step.missing)} — ask for all of it in one surface, bound to ` +
        `${step.missing.map((key) => `$${bindingFor(key)}`).join(', ')}, with one button.`,
    );
  }
  if (step.missing.length === 0 && !step.pending) {
    parts.push('Draw what it needs and move it forward.');
  }

  parts.push(
    'End every turn having moved the trip on, or having asked exactly what it takes to. ' +
      'If this stage does not apply to their trip — driving rather than flying, staying with ' +
      `family, no fixed budget — record that with save_trip (skip: ["${step.stage}"]) and go ` +
      'to the next one instead of asking a question they have already answered.',
  );

  return parts.join(' ');
}
