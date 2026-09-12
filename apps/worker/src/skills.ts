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

import roleMarkdown from '../../../prompts/role.md';
import inlineBrief from '../../../prompts/surface-inline.md';
import sidebarBrief from '../../../prompts/surface-sidebar.md';
import homeBrief from '../../../prompts/surface-home.md';
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

/**
 * The raw instructions a variant loads, joined.
 *
 * Exported for fingerprinting rather than for reading: `describeSkill` reports
 * skill *names*, which do not change when the instructions behind them do, so a
 * stamp built from those would happily call a rewritten skill unchanged.
 */
export function skillText(variant: SkillVariant): string {
  return SKILL_SOURCES[variant].join('\n');
}

export function describeAllSkills(): SkillInfo[] {
  return SKILL_VARIANTS.map(describeSkill);
}

export function isSkillVariant(value: unknown): value is SkillVariant {
  return typeof value === 'string' && (SKILL_VARIANTS as string[]).includes(value);
}

/**
 * The role and the surface briefs, read from `prompts/` rather than written here.
 *
 * They used to be template literals in this file, which was fine while this
 * file was the only thing that read them. The Python server reads them too, and
 * a second hand-typed copy of two hundred lines of prompt engineering is how
 * two implementations end up with agents that behave differently and a week of
 * wondering why. Same reason the tool descriptions live in `data/tools.json`.
 *
 * Markdown on disk, imported as text — so what is reviewed in a diff is exactly
 * what the model reads, with no escaping between the two.
 */
const ROLE = roleMarkdown.trim();

const SURFACE_BRIEFS: Record<SurfaceKind, string> = {
  inline: inlineBrief.trim(),
  sidebar: sidebarBrief.trim(),
  home: homeBrief.trim(),
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
function describeTrip(
  trip: Record<string, unknown>,
  today: string,
  surface: SurfaceKind,
): string {
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
  // "Lead the trip" and "the panel is read-only" are in direct conflict on a
  // panel turn, and the model resolves it the way it was always going to: it
  // advances the plan, in the panel, with the controls the next step needs.
  // Which the host then ignores. So the instruction is scoped — on this turn
  // the next step is somebody else's job.
  lines.push(
    surface === 'inline'
      ? `- **Do this next.** ${nextStepFor(normalized)}`
      : `- **Not this turn.** ${
          surface === 'sidebar'
            ? 'You are drawing the record, not advancing the plan. Ask for nothing here. ' +
              'The next step is asked in the conversation, on the next inline turn.'
            : 'You are drawing a standing summary, not advancing the plan. Ask for nothing ' +
              'here; the next step is asked in the conversation.'
        } For context, what is outstanding is: ${nextStepFor(normalized)}`,
  );

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
export function buildSystemPrompt(options: PromptOptions): string {
  const stable = [ROLE, ...SKILL_SOURCES[options.variant].map(body)].join('\n\n---\n\n');

  const volatile = [
    SURFACE_BRIEFS[options.surface],
    `## This turn`,
    `- Today's date is ${options.today}. Any date you suggest is after it.`,
    `- Draw into surface \`${options.surfaceId}\`.`,
    `- The host's catalog id is \`${options.catalogId}\`.`,
    ``,
    `## The trip so far`,
    describeTrip(options.trip, options.today, options.surface),
    options.originHint && !options.trip['origin']
      ? `- The browser's timezone is ${options.originHint.timeZone}, so ${options.originHint.city} ` +
        `(${options.originHint.code}) is a reasonable *suggestion* for where they are flying from. ` +
        'Offer it pre-filled and let them change it. Do not treat it as their answer.'
      : '',
  ]
    .filter(Boolean)
    .join('\n');

  // Stable first, volatile second, and that order is the whole optimisation.
  // Gemini caches a repeated prefix implicitly, so the catalog, the rules and
  // the component signatures — which are identical on every turn of every
  // conversation — are paid for once and read back thereafter. Putting the
  // trip's current state above them would move the boundary to the top of the
  // prompt and cache nothing.
  return `${stable}\n\n---\n\n${volatile}`;
}
