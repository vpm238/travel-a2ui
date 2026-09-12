#!/usr/bin/env node
/**
 * Dumps the six surface builders — the ones an MCP host and a voice call use.
 *
 * These are what a *different agent* gets when it installs the plugin: Claude
 * calls `show_flight_options` and receives A2UI, not prose. So they are the
 * whole gen-UI promise carried into somebody else's product, and they are also
 * the tools a Live session draws with, because reading four fares aloud is a
 * memory test and a screen is a clumsy way to hold a conversation.
 *
 * Each returns three things: the Express it composed, the surface it writes to,
 * and a one-line summary for the model to *say* rather than read out. The
 * summary is easy to treat as an afterthought and is not — sending the whole
 * surface back to the model would put a flight list in its context and invite
 * it to recite the list, which is the one thing this mode exists to avoid.
 *
 *   node tools/parity/surfaces-golden.mjs            # write
 *   node tools/parity/surfaces-golden.mjs --check    # fail if it moved
 */

import { execFileSync } from 'node:child_process';
import { mkdirSync, existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');
const OUT = join(here, '__golden__', 'surfaces.json');

const cache = join(root, 'node_modules', '.cache');
const entry = join(cache, 'surfaces-golden-entry.ts');
const bundle = join(cache, 'surfaces-golden.mjs');
mkdirSync(cache, { recursive: true });
writeFileSync(
  entry,
  [
    "export { buildSurface, toolExamples, MCP_TOOLS } from '../../apps/worker/src/mcp.js';",
    "export { FixtureProvider } from '../../apps/worker/src/providers/index.js';",
    "export { voiceTools, setupFrame, VOICE_BRIEF } from '../../apps/worker/src/voice.js';",
  ].join('\n'),
);
execFileSync(
  join(root, 'node_modules', '.bin', 'esbuild'),
  [
    entry,
    '--bundle',
    '--format=esm',
    '--platform=node',
    `--outfile=${bundle}`,
    '--loader:.md=text',
    '--loader:.html=text',
    '--alias:@travel-a2ui/express=./packages/express/src/index.ts',
    '--alias:@travel-a2ui/trip=./packages/trip/src/index.ts',
    '--log-level=warning',
  ],
  { cwd: root, stdio: 'inherit' },
);
const { buildSurface, toolExamples, MCP_TOOLS, FixtureProvider, voiceTools, setupFrame } =
  await import(`file://${bundle}`);

/** A fixed day, so "12 days to Madrid" does not move with the calendar. */
const TODAY = '2027-03-01';

const provider = new FixtureProvider();

/**
 * Cases chosen for the branch each one takes, not for looking like requests.
 *
 * Every builder is run in all three flows, because the flow changes the surface
 * id, the heading level and how many options fit — and a port that ignored it
 * would produce a home screen with six flights on it, which reads as a wall.
 */
const CASES = {
  'flights: inline, fully specified': [
    'show_flight_options',
    {
      destination: 'Madrid',
      origin: 'JFK',
      date: '2027-04-12',
      travelers: 2,
      cabin: 'business',
    },
  ],
  'flights: sidebar, three fit': [
    'show_flight_options',
    { destination: 'Madrid', origin: 'JFK', date: '2027-04-12', surface: 'sidebar' },
  ],
  'flights: home, two fit': [
    'show_flight_options',
    { destination: 'Madrid', origin: 'JFK', date: '2027-04-12', surface: 'home' },
  ],
  'flights: nonstop only': [
    'show_flight_options',
    { destination: 'Lisbon', origin: 'BOS', date: '2027-04-12', nonstopOnly: true },
  ],
  'flights: a cap nothing meets, so it widens and says so': [
    'show_flight_options',
    { destination: 'Tokyo', origin: 'LAX', date: '2027-04-12', maxPrice: 1 },
  ],
  'flights: no date, and not asked to guess': [
    'show_flight_options',
    { destination: 'Madrid', origin: 'JFK' },
  ],
  'flights: no date, explicitly rough': [
    'show_flight_options',
    { destination: 'Madrid', origin: 'JFK', flexible: true },
  ],
  'flights: a destination nobody knows': [
    'show_flight_options',
    { destination: 'Atlantis', origin: 'JFK', date: '2027-04-12' },
  ],

  'hotels: inline': ['show_hotel_options', { destination: 'Madrid', nights: 5 }],
  'hotels: home, two fit': [
    'show_hotel_options',
    { destination: 'Madrid', nights: 5, surface: 'home' },
  ],
  'hotels: a nightly cap nothing meets': [
    'show_hotel_options',
    { destination: 'Paris', nights: 3, maxNightly: 1 },
  ],
  'hotels: a destination nobody knows': [
    'show_hotel_options',
    { destination: 'Atlantis', nights: 3 },
  ],

  'controls: with a destination and dates': [
    'show_trip_controls',
    {
      destination: 'Madrid',
      startDate: '2027-04-12',
      endDate: '2027-04-19',
      travelers: 3,
      maxPrice: 900,
      nonstopOnly: true,
    },
  ],
  'controls: with nothing at all': ['show_trip_controls', {}],

  'itinerary: three days': [
    'show_itinerary',
    { destination: 'Madrid', days: 3, startDate: '2027-04-12' },
  ],
  'itinerary: home, one day': [
    'show_itinerary',
    { destination: 'Madrid', days: 3, startDate: '2027-04-12', surface: 'home' },
  ],
  'itinerary: more days than there are highlights': [
    'show_itinerary',
    { destination: 'Madrid', days: 7, startDate: '2027-04-12' },
  ],
  'itinerary: no start date, so it starts today': [
    'show_itinerary',
    { destination: 'Madrid', days: 2 },
  ],
  'itinerary: a destination nobody knows': ['show_itinerary', { destination: 'Atlantis' }],

  'dashboard: a trip in progress': [
    'show_trip_dashboard',
    {
      destination: 'Madrid',
      startDate: '2027-04-12',
      nights: 7,
      travelers: 2,
      budget: 4000,
      spent: 1200,
    },
  ],
  'dashboard: over budget': [
    'show_trip_dashboard',
    {
      destination: 'Madrid',
      startDate: '2027-04-12',
      nights: 7,
      travelers: 2,
      budget: 1000,
      spent: 3200,
    },
  ],
  'dashboard: no budget given, so the estimate is the budget': [
    'show_trip_dashboard',
    { destination: 'Madrid', startDate: '2027-04-12', nights: 5, travelers: 2 },
  ],
  'dashboard: no date, so no countdown': [
    'show_trip_dashboard',
    { destination: 'Madrid', nights: 5, travelers: 2 },
  ],

  'price: inline': ['show_price_summary', { destination: 'Madrid', travelers: 2, nights: 5 }],
  'price: with prices passed in': [
    'show_price_summary',
    { destination: 'Madrid', travelers: 2, nights: 5, flightPrice: 780, nightlyPrice: 190 },
  ],
  'price: home': [
    'show_price_summary',
    { destination: 'Madrid', travelers: 2, nights: 5, surface: 'home' },
  ],

  'express: whatever the model composed': [
    'render_a2ui_express',
    {
      source: 'surface("mcp")\nhead = Text("Anything", variant="h3")\nroot = Column([head])',
      surfaceId: 'mcp',
    },
  ],
};

const golden = { surfaces: {}, examples: toolExamples(), voice: {} };

for (const [name, [tool, args]] of Object.entries(CASES)) {
  try {
    const surface = await buildSurface(tool, args, provider, TODAY);
    golden.surfaces[name] = { tool, args, ...surface };
  } catch (error) {
    // A refusal is an outcome here, not a failure: "no date was given" and "I
    // have never heard of Atlantis" are both things the model has to be told
    // in words it can act on, so the message is part of the contract.
    golden.surfaces[name] = { tool, args, error: String(error.message ?? error) };
  }
}

// The tools a Live session may call, and the frame that opens one. Pinned
// because the Live API rejects an entire setup over one unsupported schema
// keyword, and the failure names the setup rather than the schema.
golden.voice.tools = voiceTools();
golden.voice.setup = setupFrame({
  model: 'gemini-2.5-flash-native-audio-preview-09-2025',
  systemInstruction: 'SYSTEM',
  voice: 'Charon',
});
golden.voice.toolNames = MCP_TOOLS.map((tool) => tool.name);

const text = `${JSON.stringify(golden, null, 2)}\n`;

if (process.argv.includes('--check')) {
  if (!existsSync(OUT)) {
    console.error(`Missing ${OUT}. Run: node tools/parity/surfaces-golden.mjs`);
    process.exit(1);
  }
  if (readFileSync(OUT, 'utf-8') !== text) {
    console.error('The surfaces golden moved. Run: node tools/parity/surfaces-golden.mjs');
    process.exit(1);
  }
  console.log(`surfaces golden: ${Object.keys(golden.surfaces).length} cases unchanged`);
} else {
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, text);
  console.log(`Wrote ${Object.keys(golden.surfaces).length} cases to ${OUT}`);
}

rmSync(bundle, { force: true });
rmSync(entry, { force: true });
