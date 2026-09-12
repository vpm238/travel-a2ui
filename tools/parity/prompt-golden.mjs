#!/usr/bin/env node
/**
 * Dumps the system prompt the agent is given, so a second implementation can be
 * held to it byte for byte.
 *
 * The prompt is the agent. Not a configuration of it — the whole of what makes
 * it refuse to price a week nobody chose, ask for everything missing in one
 * surface, and draw a read-only panel when it is drawing the panel. Two servers
 * that call the same model with different prompts are two different products,
 * and nothing about the difference looks like a bug: both answer, both draw
 * something, and only the details of what they draw diverge.
 *
 * Most of the prompt is now shared text — `prompts/*.md` and the generated
 * skills — so what this really pins is the assembly: the order of the layers,
 * where the cache breakpoint falls, and the trip description built per turn,
 * which is the part that is actually code and actually differs between two
 * implementations of it.
 *
 *   node tools/parity/prompt-golden.mjs            # write
 *   node tools/parity/prompt-golden.mjs --check    # fail if it moved
 */

import { execFileSync } from 'node:child_process';
import { mkdirSync, existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');
const OUT = join(here, '__golden__', 'prompt.json');

const cache = join(root, 'node_modules', '.cache');
const bundle = join(cache, 'prompt-golden.mjs');
mkdirSync(cache, { recursive: true });
execFileSync(
  join(root, 'node_modules', '.bin', 'esbuild'),
  [
    join(root, 'apps', 'worker', 'src', 'skills.ts'),
    '--bundle',
    '--format=esm',
    '--platform=node',
    `--outfile=${bundle}`,
    '--loader:.md=text',
    '--log-level=warning',
  ],
  { cwd: root, stdio: 'inherit' },
);
const { buildSystemPrompt, describeAllSkills } = await import(`file://${bundle}`);

const TODAY = '2027-03-01';

/**
 * Trips chosen for the branches they take through `describeTrip`, which is the
 * part of this that is code: nothing settled, something settled, everything
 * settled, something wrong with it, a stage ruled out, a route with several
 * stops.
 */
const TRIPS = {
  empty: {},
  started: { destination: 'Madrid' },
  ready: {
    origin: 'JFK',
    destination: 'Madrid',
    startDate: '2027-04-12',
    endDate: '2027-04-19',
    travelers: 2,
  },
  priced: {
    origin: 'JFK',
    destination: 'Madrid',
    startDate: '2027-04-12',
    endDate: '2027-04-19',
    travelers: 2,
    flightPrice: 780,
    nightlyPrice: 190,
    budget: 3000,
    selectedFlight: 'IB614',
  },
  broken: {
    destination: 'Madrid',
    origin: 'JFK',
    startDate: '2027-04-20',
    endDate: '2027-04-12',
    travelers: 2,
  },
  skipping: { destination: 'Madrid', origin: 'JFK', skip: ['stay', 'budget'] },
  multiCity: {
    origin: 'SFO',
    destination: 'Chicago',
    startDate: '2027-04-12',
    endDate: '2027-04-14',
    travelers: 1,
    legs: [
      { destination: 'New York', startDate: '2027-04-14', endDate: '2027-04-18' },
      { destination: 'San Francisco', startDate: '2027-04-18', travelers: 2 },
    ],
  },
};

const golden = { skills: describeAllSkills(), prompts: {} };

for (const [tripName, trip] of Object.entries(TRIPS)) {
  for (const surface of ['inline', 'sidebar', 'home']) {
    golden.prompts[`${tripName} / ${surface}`] = buildSystemPrompt({
      variant: 'express-monolithic',
      surface,
      surfaceId: surface === 'inline' ? 'inline-1' : surface,
      catalogId: 'travel',
      trip,
      today: TODAY,
    });
  }
}

// Every variant once, so a port that wires the modular skills up in the wrong
// order — or loads one file where two were meant — is caught here rather than
// by a model behaving oddly in a demo.
for (const variant of ['express-monolithic', 'express-modular', 'direct-json-monolithic']) {
  golden.prompts[`variant / ${variant}`] = buildSystemPrompt({
    variant,
    surface: 'inline',
    surfaceId: 'inline-1',
    catalogId: 'travel',
    trip: TRIPS.ready,
    today: TODAY,
  });
}

// The origin hint, which is the one conditional block in the assembly, both
// ways round: offered when no origin is known, silent when one is.
for (const [label, trip] of [
  ['offered', TRIPS.started],
  ['suppressed, because they already said', TRIPS.ready],
]) {
  golden.prompts[`origin hint / ${label}`] = buildSystemPrompt({
    variant: 'express-monolithic',
    surface: 'inline',
    surfaceId: 'inline-1',
    catalogId: 'travel',
    trip,
    today: TODAY,
    originHint: { code: 'SFO', city: 'San Francisco', timeZone: 'America/Los_Angeles' },
  });
}

const text = `${JSON.stringify(golden, null, 2)}\n`;

if (process.argv.includes('--check')) {
  if (!existsSync(OUT)) {
    console.error(`Missing ${OUT}. Run: node tools/parity/prompt-golden.mjs`);
    process.exit(1);
  }
  if (readFileSync(OUT, 'utf-8') !== text) {
    console.error(
      'The prompt golden moved.\n' +
        'A prompt change is a change to the agent, so make it deliberately, then:\n' +
        '  node tools/parity/prompt-golden.mjs',
    );
    process.exit(1);
  }
  console.log(`prompt golden: ${Object.keys(golden.prompts).length} prompts unchanged`);
} else {
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, text);
  console.log(`Wrote ${Object.keys(golden.prompts).length} prompts to ${OUT}`);
}

rmSync(bundle, { force: true });
