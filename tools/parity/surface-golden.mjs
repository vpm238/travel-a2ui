#!/usr/bin/env node
/**
 * Dumps what the server does to a surface before it goes out.
 *
 * Four passes, and every one of them exists because something asked of the
 * model was sometimes not done: fields seeded so controls open pre-filled, a
 * commit button given every path its surface edits, a night count the model
 * wrote as literal text replaced by the call that computes it, and a `change`
 * button removed from anywhere that is not the panel.
 *
 * These are the passes that keep a thin client thin — a Flutter or Swift client
 * gets a surface that is already right and gains no logic to make it so — which
 * is exactly why both servers have to do them identically. A port that seeds
 * `/trip` but forgets `/plan` ships a panel that renders blank before anything
 * is decided; one that binds commit contexts in a different order ships buttons
 * whose payload keys change between turns. Neither throws.
 *
 *   node tools/parity/surface-golden.mjs            # write
 *   node tools/parity/surface-golden.mjs --check    # fail if it moved
 */

import { execFileSync } from 'node:child_process';
import { mkdirSync, existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');
const OUT = join(here, '__golden__', 'surface.json');

const cache = join(root, 'node_modules', '.cache');
const entry = join(cache, 'surface-golden-entry.ts');
const bundle = join(cache, 'surface-golden.mjs');
mkdirSync(cache, { recursive: true });
writeFileSync(
  entry,
  [
    "export { planRows, seedSurfaceTrip, tripUpdates, STANDING_SURFACES } from '../../apps/worker/src/surface.js';",
    "export { bindCommitContext, bindDerivedLabels, stripPanelActions } from '@travel-a2ui/express';",
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
    '--alias:@travel-a2ui/express=./packages/express/src/index.ts',
    '--alias:@travel-a2ui/trip=./packages/trip/src/index.ts',
    '--log-level=warning',
  ],
  { cwd: root, stdio: 'inherit' },
);
const {
  planRows,
  seedSurfaceTrip,
  tripUpdates,
  bindCommitContext,
  bindDerivedLabels,
  stripPanelActions,
  STANDING_SURFACES,
} = await import(`file://${bundle}`);

/** Trips chosen for the rows they produce, not for looking like trips. */
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
  skipping: { destination: 'Madrid', origin: 'JFK', skip: ['stay', 'budget'] },
  multiCity: {
    origin: 'SFO',
    destination: 'Chicago',
    startDate: '2027-04-12',
    endDate: '2027-04-14',
    travelers: 1,
    legs: [
      { destination: 'New York', startDate: '2027-04-14', endDate: '2027-04-18', purpose: 'a wedding' },
      { destination: 'San Francisco', startDate: '2027-04-18', travelers: 2, needsStay: false },
    ],
  },
};

const surface = (surfaceId, components, dataModel) => [
  { version: 'v0.9.1', createSurface: { surfaceId, catalogId: 'travel', ...(dataModel ? { dataModel } : {}) } },
  { version: 'v0.9.1', updateComponents: { surfaceId, components } },
];

/** Surfaces chosen for the pass each one exercises. */
const SURFACES = {
  'editors with a button that binds nothing': () =>
    surface('inline-1', [
      { id: 'from', component: 'TextField', label: 'From', text: { path: '/trip/origin' } },
      {
        id: 'when',
        component: 'DateRangePicker',
        label: 'Dates',
        start: { path: '/trip/startDate' },
        end: { path: '/trip/endDate' },
      },
      { id: 'who', component: 'TravelerCounter', label: 'Travelers', value: { path: '/trip/travelers' } },
      { id: 'go', component: 'Button', label: 'Search', action: { event: { name: 'search_flights', context: {} } } },
      { id: 'root', component: 'Column', children: ['from', 'when', 'who', 'go'] },
    ]),

  'a button that already bound one thing itself': () =>
    surface('inline-1', [
      { id: 'from', component: 'TextField', label: 'From', text: { path: '/trip/origin' } },
      { id: 'who', component: 'TravelerCounter', label: 'Travelers', value: { path: '/trip/travelers' } },
      {
        id: 'go',
        component: 'Button',
        label: 'Search',
        action: { event: { name: 'search_flights', context: { departingFrom: { path: '/trip/origin' } } } },
      },
      { id: 'root', component: 'Column', children: ['from', 'who', 'go'] },
    ]),

  'editors and no button at all, which is a dead end': () =>
    surface('inline-1', [
      { id: 'from', component: 'TextField', label: 'From', text: { path: '/trip/origin' } },
      { id: 'who', component: 'TravelerCounter', label: 'Travelers', value: { path: '/trip/travelers' } },
      { id: 'root', component: 'Column', children: ['from', 'who'] },
    ]),

  'two buttons, both of which must carry the answer': () =>
    surface('inline-1', [
      { id: 'when', component: 'DateRangePicker', label: 'Dates', start: { path: '/trip/startDate' }, end: { path: '/trip/endDate' } },
      { id: 'a', component: 'Button', label: 'Search flights', action: { event: { name: 'search_flights', context: {} } } },
      { id: 'b', component: 'Button', label: 'Search hotels', action: { event: { name: 'search_hotels', context: {} } } },
      { id: 'root', component: 'Column', children: ['when', 'a', 'b'] },
    ]),

  'colliding key names from two different paths': () =>
    surface('inline-1', [
      { id: 'a', component: 'TextField', label: 'From', text: { path: '/trip/origin' } },
      { id: 'b', component: 'TextField', label: 'Leg from', text: { path: '/leg/origin' } },
      { id: 'go', component: 'Button', label: 'Go', action: { event: { name: 'go', context: {} } } },
      { id: 'root', component: 'Column', children: ['a', 'b', 'go'] },
    ]),

  'a night count written as literal text': () =>
    surface('inline-1', [
      {
        id: 'when',
        component: 'DateRangePicker',
        label: 'Dates',
        start: { path: '/trip/startDate' },
        end: { path: '/trip/endDate' },
        nightsLabel: '7 nights',
      },
      { id: 'root', component: 'Column', children: ['when'] },
    ]),

  'a night count the model already wrote as a template': () =>
    surface('inline-1', [
      {
        id: 'when',
        component: 'DateRangePicker',
        label: 'Dates',
        start: { path: '/trip/startDate' },
        end: { path: '/trip/endDate' },
        nightsLabel: { call: 'formatString', args: { value: '${calcNights(start:${/trip/startDate}, end:${/trip/endDate})} nights, including the wedding' } },
      },
      { id: 'root', component: 'Column', children: ['when'] },
    ]),

  'a picker whose ends are literal dates': () =>
    surface('inline-1', [
      { id: 'when', component: 'DateRangePicker', label: 'Dates', start: '2027-04-12', end: '2027-04-19', nightsLabel: '7 nights' },
      { id: 'root', component: 'Column', children: ['when'] },
    ]),

  'a change button drawn inline, where it does not belong': () =>
    surface('inline-1', [
      { id: 'ask', component: 'Text', text: 'When are you going?' },
      { id: 'label', component: 'Text', text: 'Route' },
      { id: 'change', component: 'Button', label: 'Change', action: { event: { name: 'change', context: { field: 'destination' } } } },
      { id: 'recap', component: 'Row', children: ['label', 'change'] },
      { id: 'root', component: 'Column', children: ['ask', 'recap'] },
    ]),

  'a change button alone in a row, which leaves the row empty': () =>
    surface('inline-1', [
      { id: 'ask', component: 'Text', text: 'When are you going?' },
      { id: 'change', component: 'Button', label: 'Change', action: { event: { name: 'change', context: { field: 'destination' } } } },
      { id: 'onlyChange', component: 'Row', children: ['change'] },
      { id: 'root', component: 'Column', children: ['ask', 'onlyChange'] },
    ]),

  'the same change button on the panel, where it does': () =>
    surface('sidebar', [
      { id: 'label', component: 'Text', text: 'Route' },
      { id: 'change', component: 'Button', label: 'Change', action: { event: { name: 'change', context: { field: 'destination' } } } },
      { id: 'root', component: 'Column', children: ['label', 'change'] },
    ]),

  'a surface that already seeded a value itself': () =>
    surface(
      'inline-1',
      [
        { id: 'when', component: 'DateRangePicker', label: 'Dates', start: { path: '/trip/startDate' }, end: { path: '/trip/endDate' } },
        { id: 'root', component: 'Column', children: ['when'] },
      ],
      { trip: { startDate: '2027-06-01' } },
    ),

  'a template row, whose path is a collection and not an answer': () =>
    surface('inline-1', [
      { id: 'row', component: 'Text', text: { path: 'name' } },
      { id: 'list', component: 'List', children: { path: '/hotels', componentId: 'row' } },
      { id: 'pick', component: 'TextField', label: 'Note', text: { path: '/trip/neighborhood' } },
      { id: 'go', component: 'Button', label: 'Go', action: { event: { name: 'go', context: {} } } },
      { id: 'root', component: 'Column', children: ['list', 'pick', 'go'] },
    ]),
};

const golden = { planRows: {}, tripUpdates: {}, surfaces: {} };

for (const [name, trip] of Object.entries(TRIPS)) {
  golden.planRows[name] = planRows(trip);
  golden.tripUpdates[name] = tripUpdates('sidebar', trip);
}

// The whole pipeline, in the order the agent runs it, against a trip with
// something in it — because seeding is what half these passes interact with.
for (const [name, build] of Object.entries(SURFACES)) {
  golden.surfaces[name] = stripPanelActions(
    bindDerivedLabels(bindCommitContext(seedSurfaceTrip(build(), TRIPS.ready))),
    STANDING_SURFACES,
  );
}

const text = `${JSON.stringify(golden, null, 2)}\n`;

if (process.argv.includes('--check')) {
  if (!existsSync(OUT)) {
    console.error(`Missing ${OUT}. Run: node tools/parity/surface-golden.mjs`);
    process.exit(1);
  }
  if (readFileSync(OUT, 'utf-8') !== text) {
    console.error('The surface golden moved. Run: node tools/parity/surface-golden.mjs');
    process.exit(1);
  }
  console.log(`surface golden: ${Object.keys(golden.surfaces).length} surfaces unchanged`);
} else {
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, text);
  console.log(`Wrote ${Object.keys(golden.surfaces).length} surfaces to ${OUT}`);
}

rmSync(bundle, { force: true });
rmSync(entry, { force: true });
