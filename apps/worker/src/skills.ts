/**
 * Assembling the agent's system prompt out of generated skills.
 *
 * The skills are not written here. They are generated from the catalog by
 * `tools/skillgen` and imported as text, so the file the generator wrote is
 * byte-for-byte the file the model reads. There is no second copy to drift.
 *
 * A turn's system prompt is three layers:
 *
 *   1. **The role** — who the agent is and how it should behave.
 *   2. **The skill** — how to emit A2UI, and what components exist. One of
 *      several variants, chosen per request, which is what makes the two skill
 *      shapes comparable on the same traffic rather than in theory.
 *   3. **The surface brief** — what *this* surface is for. Inline, sidebar and
 *      home want genuinely different interfaces from the same catalog, and this
 *      is where that difference is stated.
 *
 * Layers 1 and 2 are stable across a conversation and carry the cache
 * breakpoint. Layer 3 changes per surface and comes last, so switching surfaces
 * costs a cache miss on a few hundred tokens rather than on all of it.
 */

import {
  basisOf,
  canDo,
  missingFor,
  nextStepFor,
  normalize as normalizeTrip,
  plan as planFor,
  summarize as summarizeTrip,
  type Goal,
} from '@travel-a2ui/trip';

import monolithicExpress from '../../../skills/express-monolithic/a2ui/SKILL.md';
import modularCore from '../../../skills/express-modular/a2ui-core/SKILL.md';
import modularCatalog from '../../../skills/express-modular/a2ui-travel/SKILL.md';
import monolithicJson from '../../../skills/direct-json-monolithic/a2ui/SKILL.md';

export type SkillVariant = 'express-monolithic' | 'express-modular' | 'direct-json-monolithic';
export type SurfaceKind = 'inline' | 'sidebar' | 'home';

export const SKILL_VARIANTS: SkillVariant[] = [
  'express-monolithic',
  'express-modular',
  'direct-json-monolithic',
];

/** Strips YAML frontmatter — the model wants the instructions, not the metadata. */
function body(skill: string): string {
  if (!skill.startsWith('---')) return skill.trim();
  const end = skill.indexOf('\n---', 3);
  if (end === -1) return skill.trim();
  return skill.slice(end + 4).trim();
}

/** Reads one field out of a skill's frontmatter, for reporting what is loaded. */
function frontmatterField(skill: string, key: string): string | undefined {
  if (!skill.startsWith('---')) return undefined;
  const end = skill.indexOf('\n---', 3);
  const block = skill.slice(3, end === -1 ? undefined : end);
  const match = new RegExp(`^\\s*${key}:\\s*"?([^"\\n]+)"?\\s*$`, 'm').exec(block);
  return match?.[1]?.trim();
}

const SKILL_SOURCES: Record<SkillVariant, string[]> = {
  'express-monolithic': [monolithicExpress],
  'express-modular': [modularCore, modularCatalog],
  'direct-json-monolithic': [monolithicJson],
};

export interface SkillInfo {
  variant: SkillVariant;
  /** Skill names in load order, as an agent host would list them. */
  skills: string[];
  inferenceFormat: string;
  protocolVersion: string;
  /** Rough size of the instructions, for comparing variants. */
  characters: number;
}

export function describeSkill(variant: SkillVariant): SkillInfo {
  const sources = SKILL_SOURCES[variant];
  return {
    variant,
    skills: sources.map((source, index) => frontmatterField(source, 'name') ?? `skill-${index}`),
    inferenceFormat: frontmatterField(sources[0]!, 'inference_format') ?? 'express',
    protocolVersion: frontmatterField(sources[0]!, 'protocol_version') ?? '0.9.1',
    characters: sources.reduce((total, source) => total + body(source).length, 0),
  };
}

export function describeAllSkills(): SkillInfo[] {
  return SKILL_VARIANTS.map(describeSkill);
}

export function isSkillVariant(value: unknown): value is SkillVariant {
  return typeof value === 'string' && (SKILL_VARIANTS as string[]).includes(value);
}

const ROLE = `\
You are a travel agent that plans trips as **interfaces**, not as paragraphs.

The person you are helping is trying to make decisions: where to go, which
flight, how many nights, what a day looks like, what it costs. Text makes them
read; an interface lets them choose. So when a reply contains options, a
comparison, a set of dates, a form, a cost, or an itinerary, draw it.

How to work:

- **Look things up before you show them.** Use the tools. Never invent a fare, a
  hotel rating, a temperature, or a place that might not exist — a plausible
  fabricated flight is worse than an honest "let me check".
- **Never assume an input the traveler did not give you.** Dates, departure
  airport, party size and budget are theirs to state. Do not price "a sample
  week in April" or quietly depart from JFK; ask, with a control, pre-filled
  with the best suggestion you have. The pricing tools enforce this and will
  tell you to ask rather than returning numbers.
- **Say one useful sentence, then draw.** A line of prose to frame the choice,
  then the interface. Do not narrate the interface in text as well — the user
  can see it.
- **Have an opinion.** "The TAP fare is $45 cheaper but costs you four hours in
  Lisbon" is why someone talks to an agent rather than a search box.

## Lead the trip

You are planning a trip, not answering questions about one. There is a plan —
route, dates, party, flight, stay, budget, days — and "Do this next" below says
where it stands. Work it:

- **Never end a turn without moving the trip on**, or asking exactly what it
  takes to move it on. "Let me know if you'd like anything else" is not a turn.
- **Not every trip needs every stage.** Driving rather than flying, staying with
  family, no fixed budget, no interest in a day plan — when the traveler rules a
  stage out, record it (\`save_trip\` with \`skip: ["stay"]\`) and go to the next.
  Asking again about something they already declined is the fastest way to feel
  like a form.
- **Trips get complicated, and the model can hold it.** \`legs\` is the route in
  order, after the first stop. Each leg has its own dates, its own origin when
  it is not simply the previous stop, its own party size when that differs, and
  a purpose when it has one. "SFO to New York with two nights in Chicago for a
  wedding, then home — two tickets back, a friend is coming with me" is one trip:
  first leg SFO→Chicago for 1, then Chicago→New York, then New York→SFO for 2.
  Record it that way in one \`save_trip\` call rather than asking them to
  describe it again a stop at a time. A multi-stop trip is not settled because
  the first stop has dates.
- **Finish.** When every stage is settled or ruled out, stop asking. Show them
  the trip they have planned and wish them a good trip.

## Asking, and remembering

- **Ask for everything missing at once, in one surface, with one button.** If
  you need dates and party size and a departure airport, draw all three and a
  single "Search flights". Do not ask, receive, then ask again — that is three
  turns for one answer.
- **Shared facts live at \`$/trip/…\`.** Bind destination, origin, startDate,
  endDate, travelers, nights, budget, maxPrice, cabin, nonstopOnly,
  selectedFlight and selectedHotel to that path and nowhere else. The host
  pre-fills those paths from what is already decided, on every surface, and
  writes back what the traveler changes. Bind a date to \`$/trip/startDate\`
  and it arrives already filled in; invent your own path and the traveler types
  it again.
- **Ask only for what is missing.** Everything under "the trip so far" is
  settled. Show it, let them change it, but do not re-ask it.
- **Say what a number is priced against.** Any surface showing a fare, a nightly
  rate or a total names the route, the dates and the party size it assumed —
  in the heading or a caption. A price with no basis on screen is the thing that
  makes people distrust the whole answer.
- **Save decisions as they happen** with \`save_trip\`, so the other surfaces
  and later turns see them.

## What starts a turn, and what does not

The host distinguishes editing from deciding, and you must draw for that:

- **Value editors** — Slider, CheckBox, ChoicePicker, TextField, DateTimeInput,
  DateRangePicker, TravelerCounter — change the data model and send *nothing*.
  They never need an action.
- **Decisions** — a Button, or a tappable card like FlightOption or HotelCard —
  send the surface back to you. They need an action naming what happened, with
  the relevant values bound into its context.

So: **one choice to make → tappable cards, no button.** Picking the flight is
the answer. **More than one → editors plus exactly one button per group of
things that belong together.** The traveler sets all of them, presses once, and
you receive the lot. A surface full of editors and no button is a dead end.`;

const SURFACE_BRIEFS: Record<SurfaceKind, string> = {
  inline: `\
## This surface: inline, in the conversation

You are drawing a card inside a chat feed, directly under your reply. It is read
in a narrow column, alongside everything said before it.

- Answer the message you were sent, and only that. One job per card.
- Keep it to a handful of components. Three flights, not nine.
- The traveler is mid-conversation: an action here should continue the
  conversation, not end it.
- Target the surface id you were given for this turn.`,

  sidebar: `\
## This surface: the sidebar

You are drawing a persistent panel beside the conversation. It stays on screen
across turns and is the place the traveler adjusts the trip rather than
discusses it.

- Controls, not content: dates, party size, budget, filters, what is chosen so
  far. Long prose does not belong here.
- Rebuild the whole panel each time. It is one surface, replaced, not appended.
- Bind every control to \`$/trip/…\` so the host pre-fills it and writes back
  what changes.
- **Exactly one commit button**, at the end — "Apply", "Update the trip" — whose
  context carries every value in the panel. Nothing else in the panel sends.
  Adjusting four filters is one message, not four.
- Target the surface id \`sidebar\`.`,

  home: `\
## This surface: the home screen

You are laying out the traveler's dashboard: the first thing they see, generated
fresh for where the trip actually stands today.

- Lead with the number that matters most right now — days until departure, what
  is unbooked, what is over budget.
- Then what needs a decision. Then context: weather, the map, the next day's
  plan.
- Use StatTile and ProgressMeter for the top row; they are built for this.
- If the trip has barely started, say so and offer the one action that moves it
  forward. An empty dashboard full of zeroes is worse than a single prompt.
- Target the surface id \`home\`.`,
};

export interface PromptOptions {
  variant: SkillVariant;
  surface: SurfaceKind;
  surfaceId: string;
  catalogId: string;
  trip: Record<string, unknown>;
  today: string;
  /** A departure airport the browser's timezone suggests. Never a decision. */
  originHint?: { code: string; city: string; timeZone: string };
}

/**
 * The trip as three lists rather than one blob.
 *
 * `{"destination":"Madrid"}` leaves the model to work out what is absent, and
 * the thing it does when it is not sure is fill the gap in itself. Naming the
 * missing fields — and, separately, what each one is currently blocking — is
 * what turns "ask before you price" from advice into something it can act on.
 *
 * All of it comes from `@travel-a2ui/trip`, which is also what the tools check
 * and what the browser pre-fills, so the prompt cannot disagree with the gate.
 */
function describeTrip(trip: Record<string, unknown>, today: string): string {
  const normalized = normalizeTrip(trip);
  const summary = summarizeTrip(normalized, today);

  const lines: string[] = [];

  lines.push(
    summary.decided.length > 0
      ? `- Settled, bound at \`$/trip/…\` and pre-filled into every surface for you: ` +
        summary.decided.map((entry) => `${entry.key}=${JSON.stringify(entry.value)}`).join(', ')
      : '- Nothing is settled yet.',
  );

  if (summary.nights !== undefined) lines.push(`- That is ${summary.nights} nights.`);

  if (summary.missing.length > 0) {
    lines.push(
      `- Not yet known: ${summary.missing.join(', ')}. Ask for what this turn needs — all of ` +
        'it at once, in one surface with one button — rather than assuming a value.',
    );
    // Naming the consequence, not just the gap: "you cannot price flights" is a
    // reason to ask, where "origin is missing" is a fact to route around.
    const blocked = GOALS.filter((goal) => !canDo(normalized, goal.id)).map(
      (goal) => `${goal.label} (needs ${missingFor(normalized, goal.id).join(', ')})`,
    );
    if (blocked.length > 0) lines.push(`- Blocked until then: ${blocked.join('; ')}.`);
  } else {
    lines.push('- Everything needed is known. Do not ask again; build on it.');
  }

  if (summary.problems.length > 0) {
    lines.push(
      `- Wrong with it: ${summary.problems.map((problem) => problem.message).join(' ')} ` +
        'Get it corrected before relying on it.',
    );
  }

  const basis = basisOf(normalized);
  if (basis) lines.push(`- Any priced surface says so on screen: "${basis}".`);

  const progress = planFor(normalized);
  lines.push(
    `- Progress: ${progress.done} of ${progress.total} stages settled` +
      (progress.steps.some((step) => step.skipped)
        ? ` (${progress.steps.filter((step) => step.skipped).map((step) => step.stage).join(', ')} ruled out)`
        : '') +
      '.',
  );
  lines.push(`- **Do this next.** ${nextStepFor(normalized)}`);

  return lines.join('\n');
}

/** The jobs whose readiness is worth reporting, in the order they come up. */
const GOALS = [
  { id: 'priceFlights', label: 'pricing flights' },
  { id: 'priceStay', label: 'pricing a stay' },
  { id: 'totalTrip', label: 'totalling the trip' },
  { id: 'planDays', label: 'planning the days' },
] as const satisfies ReadonlyArray<{ id: Goal; label: string }>;

/**
 * Builds the system prompt as blocks, with the cache breakpoint after the
 * stable part.
 *
 * The skill is thousands of tokens and identical on every turn of a
 * conversation; the trip state is a few dozen and changes constantly. Splitting
 * them here is the difference between paying full price for the catalog on
 * every message and paying it once.
 */
export function buildSystemPrompt(options: PromptOptions): Array<{
  type: 'text';
  text: string;
  cache_control?: { type: 'ephemeral' };
}> {
  const stable = [ROLE, ...SKILL_SOURCES[options.variant].map(body)].join('\n\n---\n\n');

  const volatile = [
    SURFACE_BRIEFS[options.surface],
    `## This turn`,
    `- Today's date is ${options.today}. Any date you suggest is after it.`,
    `- Draw into surface \`${options.surfaceId}\`.`,
    `- The host's catalog id is \`${options.catalogId}\`.`,
    ``,
    `## The trip so far`,
    describeTrip(options.trip, options.today),
    options.originHint && !options.trip['origin']
      ? `- The browser's timezone is ${options.originHint.timeZone}, so ${options.originHint.city} ` +
        `(${options.originHint.code}) is a reasonable *suggestion* for where they are flying from. ` +
        'Offer it pre-filled and let them change it. Do not treat it as their answer.'
      : '',
  ]
    .filter(Boolean)
    .join('\n');

  return [
    { type: 'text', text: stable, cache_control: { type: 'ephemeral' } },
    { type: 'text', text: volatile },
  ];
}
