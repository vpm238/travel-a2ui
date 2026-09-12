#!/usr/bin/env node
/**
 * Dumps what the eight tools answer, so a second implementation can be held to it.
 *
 * The trip golden pins the model underneath and `apps/worker/test/__golden__`
 * pins the providers underneath that. Neither pins the layer between them,
 * which is where the agent's manners live: when a tool refuses to price a trip
 * with no dates, what it says to the model when it does, which stop of a
 * multi-city route a call is about, and what a saved trip reports still
 * missing. That layer is nearly all judgement and none of it is generated, so
 * it is precisely the part where two implementations drift without either
 * looking wrong.
 *
 * It matters more than it looks. Every one of these results is read by a model
 * and turned into a surface. A port that returns the same flights under a
 * different key, or drops the sentence telling the model to draw the controls
 * and wait, produces an agent that is subtly worse at its job while every test
 * about flights still passes.
 *
 * The TypeScript is the incumbent and gets to be right. The Python port has to
 * reproduce this file exactly. When the TypeScript goes away the golden stays,
 * as the specification of what these tools say.
 *
 *   node tools/parity/tools-golden.mjs            # write
 *   node tools/parity/tools-golden.mjs --check    # fail if it moved
 */

import { execFileSync } from 'node:child_process';
import { mkdirSync, existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');
const OUT = join(here, '__golden__', 'tools.json');

/**
 * The Worker's tools are TypeScript with workspace imports and no build step of
 * their own — `wrangler` bundles them on deploy. So bundle them the same way
 * here rather than adding a second build output that could disagree with what
 * ships.
 */
const cache = join(root, 'node_modules', '.cache');
const entry = join(cache, 'tools-golden-entry.ts');
const bundle = join(cache, 'tools-golden.mjs');
mkdirSync(cache, { recursive: true });
writeFileSync(
  entry,
  "export { runTool } from '../../apps/worker/src/tools.js';\n" +
    "export { FixtureProvider } from '../../apps/worker/src/providers/index.js';\n",
);
execFileSync(
  join(root, 'node_modules', '.bin', 'esbuild'),
  [entry, '--bundle', '--format=esm', '--platform=node', `--outfile=${bundle}`, '--log-level=warning'],
  { cwd: root, stdio: 'inherit' },
);
const { runTool, FixtureProvider } = await import(`file://${bundle}`);

/** A fixed day, so the past-date checks in `save_trip` do not rot overnight. */
const TODAY = '2027-03-01';

/**
 * The fixtures, whatever a deployment would have picked.
 *
 * Going through the real provider rather than a stub is the point: the golden
 * then covers the seam between the tools and the data as well as the tools
 * themselves, and a port that reads `outcome.items` where it should read
 * `outcome.note` is caught here rather than on screen.
 */
const PROVIDER = new FixtureProvider();

const cases = [
  // ---- Refusing to invent, which is the behaviour most worth pinning -------
  ['flights with nothing saved', 'search_flights', { destination: 'Madrid' }, {}],
  [
    'flights with nothing saved, but explicitly rough',
    'search_flights',
    { destination: 'Madrid', flexible: true },
    {},
  ],
  [
    'flights against a fully saved trip',
    'search_flights',
    { destination: 'Madrid' },
    { origin: 'JFK', destination: 'Madrid', startDate: '2027-04-12', endDate: '2027-04-19', travelers: 2 },
  ],
  [
    'flights, nonstop only, business',
    'search_flights',
    { destination: 'Madrid', nonstopOnly: true, cabin: 'business' },
    { origin: 'JFK', startDate: '2027-04-12', endDate: '2027-04-19', travelers: 2 },
  ],
  [
    'flights under a cap nothing meets',
    'search_flights',
    { destination: 'Tokyo', maxPrice: 1 },
    { origin: 'LAX', startDate: '2027-04-12', endDate: '2027-04-19', travelers: 1 },
  ],
  [
    'flights somewhere the agent does not know',
    'search_flights',
    { destination: 'Atlantis' },
    { origin: 'JFK', startDate: '2027-04-12', endDate: '2027-04-19', travelers: 1 },
  ],

  // ---- Which stop of the route a call is about ----------------------------
  [
    'flights for the second leg, which has its own party and origin',
    'search_flights',
    { destination: 'Lisbon' },
    {
      origin: 'JFK',
      destination: 'Madrid',
      startDate: '2027-04-12',
      endDate: '2027-04-19',
      travelers: 2,
      legs: [
        { destination: 'Madrid', startDate: '2027-04-12', endDate: '2027-04-16' },
        { destination: 'Lisbon', startDate: '2027-04-16', endDate: '2027-04-19', travelers: 3 },
      ],
    },
  ],

  // ---- Stays ---------------------------------------------------------------
  ['hotels with nothing saved', 'search_hotels', { destination: 'Madrid' }, {}],
  [
    'hotels with an explicit night count and nothing saved',
    'search_hotels',
    { destination: 'Madrid', nights: 4 },
    {},
  ],
  [
    'hotels against a saved stay',
    'search_hotels',
    { destination: 'Madrid' },
    { origin: 'JFK', destination: 'Madrid', startDate: '2027-04-12', endDate: '2027-04-19', travelers: 2 },
  ],
  [
    'hotels under a nightly cap nothing meets',
    'search_hotels',
    { destination: 'Paris', maxNightly: 1 },
    { origin: 'JFK', destination: 'Paris', startDate: '2027-04-12', endDate: '2027-04-15', travelers: 2 },
  ],
  ['hotels somewhere the agent does not know', 'search_hotels', { destination: 'Atlantis', nights: 3 }, {}],

  // ---- Reference data ------------------------------------------------------
  ['every destination', 'get_destination', {}, {}],
  ['one destination', 'get_destination', { destination: 'Madrid' }, {}],
  ['a destination by airport code', 'get_destination', { destination: 'MAD' }, {}],
  ['a destination nobody knows', 'get_destination', { destination: 'Atlantis' }, {}],
  ['weather', 'get_weather', { destination: 'Madrid', startDate: '2027-04-12', days: 5 }, {}],
  ['weather somewhere the agent does not know', 'get_weather', { destination: 'Atlantis' }, {}],

  // ---- Totals --------------------------------------------------------------
  ['a total with nothing saved', 'estimate_cost', {}, {}],
  [
    'a total against a saved trip with prices chosen',
    'estimate_cost',
    {},
    {
      origin: 'JFK',
      destination: 'Madrid',
      startDate: '2027-04-12',
      endDate: '2027-04-19',
      travelers: 2,
      flightPrice: 780,
      nightlyPrice: 190,
    },
  ],
  [
    'a total with prices passed rather than saved',
    'estimate_cost',
    { destination: 'Madrid', flightPrice: 640, nightlyPrice: 150, nights: 4, flexible: true },
    {},
  ],

  // ---- Writes --------------------------------------------------------------
  ['saving a trip', 'save_trip', { destination: 'Madrid', origin: 'JFK', travelers: 2 }, {}],
  [
    'saving dates that end before they start',
    'save_trip',
    { startDate: '2027-04-20', endDate: '2027-04-12' },
    { destination: 'Madrid', origin: 'JFK' },
  ],
  ['saving a date already past', 'save_trip', { startDate: '2020-01-01' }, { destination: 'Madrid' }],
  [
    'saving a trip that is over budget, which is a real state and not a mistake',
    'save_trip',
    { budget: 100 },
    { destination: 'Madrid', origin: 'JFK', travelers: 2, flightPrice: 780, nightlyPrice: 190, startDate: '2027-04-12', endDate: '2027-04-19' },
  ],
  [
    'releasing a decision',
    'release_decision',
    { fields: ['startDate', 'endDate'] },
    { destination: 'Madrid', origin: 'JFK', startDate: '2027-04-12', endDate: '2027-04-19', travelers: 2 },
  ],
  [
    'releasing something that was never set',
    'release_decision',
    { fields: ['selectedHotel'] },
    { destination: 'Madrid' },
  ],
  [
    'putting a skipped stage back',
    'release_decision',
    { stages: ['stay'] },
    { destination: 'Madrid', skipped: ['stay'] },
  ],

  // ---- Reads and the unknown ----------------------------------------------
  ['reading the trip back', 'get_trip', {}, { destination: 'Madrid', travelers: 2 }],
  ['a tool that does not exist', 'no_such_tool', {}, {}],
];

const golden = {};
for (const [name, tool, input, trip] of cases) {
  const state = structuredClone(trip);
  const saved = [];
  const context = {
    trip: state,
    saveTrip(patch) {
      saved.push(structuredClone(patch));
      Object.assign(state, patch);
    },
    provider: PROVIDER,
    today: TODAY,
  };
  const outcome = await runTool(tool, input, context);
  golden[name] = {
    tool,
    input,
    // Recorded rather than left to the reader: three of these tools write, so
    // the trip after the call is not the trip before it, and a second
    // implementation needs the *before* to replay the case at all. Keeping it
    // here rather than in a table beside the port is what stops the two from
    // drifting into testing different things.
    tripBefore: trip,
    result: outcome.result,
    isError: outcome.isError,
    // The trip after the call, because a port that returns the right thing
    // while saving the wrong one is still broken.
    trip: state,
    saved,
  };
}

const text = `${JSON.stringify(golden, null, 2)}\n`;

if (process.argv.includes('--check')) {
  if (!existsSync(OUT)) {
    console.error(`Missing ${OUT}. Run: node tools/parity/tools-golden.mjs`);
    process.exit(1);
  }
  if (readFileSync(OUT, 'utf-8') !== text) {
    console.error(
      'The tools golden moved.\n' +
        'If the change is deliberate, rewrite it and port the same change to Python:\n' +
        '  node tools/parity/tools-golden.mjs',
    );
    process.exit(1);
  }
  console.log(`tools golden: ${Object.keys(golden).length} cases unchanged`);
} else {
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, text);
  console.log(`Wrote ${Object.keys(golden).length} cases to ${OUT}`);
}

rmSync(bundle, { force: true });
rmSync(entry, { force: true });
