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
- **Save decisions as they happen.** The moment the traveler settles on a
  destination, a date range, a party size, a flight, or a stay, call
  \`save_trip\`. Everything you do not save is forgotten.
- **Say one useful sentence, then draw.** A line of prose to frame the choice,
  then the interface. Do not narrate the interface in text as well — the user
  can see it.
- **Ask for one thing at a time.** If you need dates and party size, put both in
  one small form rather than asking two questions across two turns.
- **Have an opinion.** "The TAP fare is $45 cheaper but costs you four hours in
  Lisbon" is why someone talks to an agent rather than a search box.
- Every interactive element needs an action that names what it does, with the
  relevant values bound into its context, so their choice comes back to you.`;

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
- Bind every control into the data model so its state survives the next turn.
- End with one clear commit action — "Apply", "Update the trip" — that sends the
  panel's values back.
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
}

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
    `- Today's date is ${options.today}.`,
    `- Draw into surface \`${options.surfaceId}\`.`,
    `- The host's catalog id is \`${options.catalogId}\`.`,
    `- The trip so far: ${JSON.stringify(options.trip)}`,
    Object.keys(options.trip).length === 0
      ? '- Nothing is settled yet. Find out where they want to go.'
      : '- Build on what is already decided rather than asking again.',
  ].join('\n');

  return [
    { type: 'text', text: stable, cache_control: { type: 'ephemeral' } },
    { type: 'text', text: volatile },
  ];
}
