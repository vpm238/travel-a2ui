#!/usr/bin/env node
/**
 * Dumps what the trip model does, so a second implementation can be held to it.
 *
 * The trip model is the one piece of this project that is neither generated
 * from the catalog nor provided by the SDK: 1,090 lines of judgement about what
 * a trip is, which fields block which goals, and what to ask for next. Moving it
 * to Python is therefore the one port with no reference implementation to check
 * against — exactly the situation that produces two subtly different agents and
 * a fortnight of wondering why.
 *
 * So this writes down the answers. The TypeScript model is the incumbent and
 * gets to be right; the Python port has to reproduce this file byte for byte.
 * When the TypeScript goes away, the golden stays as the specification.
 *
 *   node tools/parity/trip-golden.mjs            # write
 *   node tools/parity/trip-golden.mjs --check    # fail if it moved
 */

import { mkdirSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  FIELDS,
  REQUIREMENTS,
  STAGES,
  TRIP_KEYS,
  askFor,
  basisOf,
  bindingFor,
  canDo,
  coerce,
  confirm,
  decisionShape,
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
} from '../../packages/trip/dist/index.js';

const here = dirname(fileURLToPath(import.meta.url));
const OUT = join(here, '__golden__', 'trip.json');

/** A fixed day, so `daysUntil` and the plan do not move with the calendar. */
const TODAY = '2027-03-01';

/**
 * Trips chosen for the decisions they force, not for looking like trips.
 */
const TRIPS = {
  empty: {},
  'destination only': { destination: 'Madrid' },
  'ready to price flights': {
    destination: 'Madrid',
    origin: 'JFK',
    startDate: '2027-04-12',
    endDate: '2027-04-19',
    travelers: 2,
  },
  'dates backwards': {
    destination: 'Madrid',
    origin: 'JFK',
    startDate: '2027-04-19',
    endDate: '2027-04-12',
    travelers: 2,
  },
  'in the past': {
    destination: 'Madrid',
    origin: 'JFK',
    startDate: '2020-04-12',
    endDate: '2020-04-19',
    travelers: 2,
  },
  assumed: {
    destination: 'Madrid',
    origin: 'JFK',
    travelers: 2,
    assumed: ['travelers'],
  },
  chosen: {
    destination: 'Madrid',
    origin: 'JFK',
    startDate: '2027-04-12',
    endDate: '2027-04-19',
    travelers: 2,
    selectedFlight: 'IB426',
    flightPrice: 352,
    selectedHotel: 'h_MAD_1',
    nightlyPrice: 140,
  },
  'multi-leg, party varies': {
    origin: 'SFO',
    destination: 'Chicago',
    startDate: '2027-04-10',
    endDate: '2027-04-12',
    travelers: 1,
    legs: [
      { destination: 'New York', startDate: '2027-04-12', endDate: '2027-04-16' },
      { destination: 'SFO', startDate: '2027-04-16', travelers: 2 },
    ],
  },
  'skipped a stage': {
    destination: 'Madrid',
    origin: 'JFK',
    startDate: '2027-04-12',
    endDate: '2027-04-19',
    travelers: 2,
    skipped: ['stay'],
  },
};

/** Values a model or a surface really sends, including the wrong shapes. */
const COERCIONS = [
  ['travelers', '3'],
  ['travelers', 3.7],
  ['travelers', ['4']],
  ['travelers', 'lots'],
  ['startDate', '2027-04-12T00:00:00Z'],
  ['startDate', 'not a date'],
  ['cabin', ['business']],
  ['cabin', 'BUSINESS'],
  ['cabin', 'spaceship'],
  ['destination', '  Madrid  '],
  ['nonstopOnly', 'true'],
  ['nonstopOnly', false],
  ['maxFare', '450'],
  ['legs', [{ destination: 'Lisbon' }]],
  ['legs', { destination: 'Lisbon' }],
  ['assumed', ['travelers', 'nonsense']],
  ['unknownKey', 'x'],
];

const GOALS = Object.keys(REQUIREMENTS);

const answers = {
  model: {
    fields: FIELDS,
    stages: STAGES,
    tripKeys: TRIP_KEYS,
    requirements: REQUIREMENTS,
    bindings: Object.fromEntries(TRIP_KEYS.map((key) => [key, bindingFor(key)])),
  },
  coerce: COERCIONS.map(([key, value]) => ({
    key,
    input: value,
    output: coerce(key, value) ?? null,
  })),
  trips: Object.fromEntries(
    Object.entries(TRIPS).map(([name, raw]) => {
      const trip = normalize(raw);
      return [
        name,
        {
          normalize: trip,
          nights: nights(trip) ?? null,
          problems: problems(trip, TODAY),
          missingFor: Object.fromEntries(GOALS.map((goal) => [goal, missingFor(trip, goal)])),
          canDo: Object.fromEntries(GOALS.map((goal) => [goal, canDo(trip, goal)])),
          summarize: summarize(trip, TODAY),
          basisOf: basisOf(trip),
          plan: plan(trip),
          nextStepFor: nextStepFor(trip),
          stops: stops(trip),
          stayStatus: stayStatus(trip),
          partyVaries: partyVaries(trip),
          decisionShape: decisionShape(trip),
        },
      ];
    }),
  ),
  askFor: [
    askFor([]),
    askFor(['destination']),
    askFor(['destination', 'origin']),
    askFor(['destination', 'origin', 'startDate']),
  ],
  merge: [
    { into: {}, patch: { destination: 'Madrid' } },
    { into: { destination: 'Madrid' }, patch: { destination: 'Lisbon' } },
    { into: { travelers: 2, assumed: ['travelers'] }, patch: { travelers: 3 } },
    { into: { destination: 'Madrid' }, patch: { legs: [{ destination: 'Lisbon' }] } },
    { into: { destination: 'Madrid' }, patch: null },
  ].map((step) => ({ ...step, result: merge(normalize(step.into), step.patch) })),
  confirm: [
    {
      trip: { travelers: 2, assumed: ['travelers', 'cabin'] },
      fields: ['travelers'],
    },
  ].map((step) => ({ ...step, result: confirm(normalize(step.trip), step.fields) })),
  release: [
    { trip: TRIPS.chosen, keys: ['startDate'] },
    { trip: TRIPS.chosen, keys: ['destination'] },
    { trip: TRIPS.chosen, keys: [] },
  ].map((step) => {
    const { trip, cleared } = release(normalize(step.trip), step.keys);
    return { keys: step.keys, trip, cleared };
  }),
  unskip: [{ trip: TRIPS['skipped a stage'], stage: 'stay' }].map((step) => ({
    stage: step.stage,
    result: unskip(normalize(step.trip), step.stage),
  })),
};

const body = `${JSON.stringify(answers, null, 2)}\n`;

if (process.argv.includes('--check')) {
  if (!existsSync(OUT)) {
    console.error(`No golden at ${OUT}. Run: node tools/parity/trip-golden.mjs`);
    process.exit(1);
  }
  if (readFileSync(OUT, 'utf8') !== body) {
    console.error('The trip model has changed. Read the diff, then regenerate:');
    console.error('  node tools/parity/trip-golden.mjs');
    process.exit(1);
  }
  console.log('The trip model matches its golden.');
} else {
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, body, 'utf8');
  console.log(`Wrote ${OUT}`);
}
