#!/usr/bin/env node
/**
 * The agent, evaluated against the real model.
 *
 * The end-to-end suites in `tools/e2e` script the model, which makes them free,
 * deterministic and CI-safe — and means they prove the *host* behaves, not the
 * agent. They cannot tell you whether it asks before it prices, whether it puts
 * every missing field in one surface, or whether it draws a control in a panel
 * that is supposed to be read-only. Those are the claims worth checking, and
 * only a live turn checks them.
 *
 * So this sends real messages to a real model and grades what comes back.
 *
 * **Nothing here is judged by another model.** Every assertion is mechanical,
 * read off the SSE stream and the compiled A2UI: which tools were called with
 * what, which components a surface contains, whether any editor carries an
 * action, how many buttons there are, what the trip ended up holding. A grader
 * that is itself a language model would make this suite exactly as trustworthy
 * as the thing it is grading.
 *
 *   ANTHROPIC_API_KEY=sk-ant-… node tools/eval/live.mjs
 *   … --only panel            run one scenario
 *   … --model claude-sonnet-5 grade a cheaper model
 *   … --json report.json      machine-readable results
 *
 * It costs real money — roughly $0.40 a full run on Opus 5 — so it is not in
 * CI. It is what you run before believing a claim about the agent's behaviour.
 */

const BASE = (process.env.BASE_URL ?? 'http://127.0.0.1:8787').replace(/\/$/, '');
const KEY = process.env.ANTHROPIC_API_KEY ?? '';
const arg = (flag) => {
  const index = process.argv.indexOf(flag);
  return index === -1 ? undefined : process.argv[index + 1];
};
const MODEL = arg('--model') ?? 'claude-opus-5';
const ONLY = arg('--only');
const JSON_OUT = arg('--json');

if (!KEY) {
  console.error('ANTHROPIC_API_KEY is required: this suite calls the real model.');
  process.exit(2);
}

// ------------------------------------------------------------ reading a turn

/** Components that edit a value. A panel containing one has failed. */
const EDITORS = new Set([
  'TextField',
  'CheckBox',
  'ChoicePicker',
  'Slider',
  'DateTimeInput',
  'DateRangePicker',
  'TravelerCounter',
]);

/** Components that make a decision when tapped. */
const DECIDERS = new Set(['Button', 'FlightOption', 'HotelCard', 'ActivityItem', 'MapPreview']);

/**
 * Sends one turn and collects everything observable about it.
 *
 * `trip` is delivered as `surfaceState`, which the Worker merges into the trip
 * before building the prompt — the same path a committed surface takes. It is
 * how a scenario starts from a half-planned trip without paying for the turns
 * that would have planned it.
 */
async function turn({ message, surface = 'inline', surfaceId, trip, session }) {
  const response = await fetch(`${BASE}/api/chat`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-anthropic-key': KEY },
    body: JSON.stringify({
      sessionId: session,
      message,
      surface,
      surfaceId: surfaceId ?? (surface === 'inline' ? 'inline-1' : surface),
      model: MODEL,
      effort: 'medium',
      client: { timeZone: 'America/Los_Angeles', locale: 'en-US' },
      ...(trip ? { surfaceState: { trip } } : {}),
    }),
  });

  if (!response.ok) throw new Error(`HTTP ${response.status}: ${(await response.text()).slice(0, 200)}`);

  const events = [];
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let boundary = buffer.indexOf('\n\n');
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf('\n\n');
      const payload = frame
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
        .join('\n');
      if (payload) {
        try {
          events.push(JSON.parse(payload));
        } catch {
          /* a frame we cannot parse is not the agent's fault */
        }
      }
    }
  }

  const prose = events
    .filter((event) => event.type === 'text')
    .map((event) => event.delta)
    .join('');

  // The last `ui` event per surface is the finished one; earlier ones are the
  // same surface mid-stream.
  const bySurface = new Map();
  for (const event of events) {
    if (event.type === 'ui') bySurface.set(event.surfaceId, event.messages);
  }

  const components = [...bySurface.values()].flatMap((messages) =>
    messages.flatMap((entry) => (entry.updateComponents ? entry.updateComponents.components : [])),
  );

  const usage = events.filter((event) => event.type === 'usage');

  return {
    events,
    prose,
    components,
    kinds: components.map((component) => component.component),
    tools: events
      .filter((event) => event.type === 'tool')
      .map((event) => ({ name: event.name, input: event.input })),
    results: events.filter((event) => event.type === 'tool_result').map((event) => event.result),
    trip: events.filter((event) => event.type === 'trip').at(-1)?.trip ?? {},
    errors: events.filter((event) => event.type === 'error' || event.type === 'ui_error'),
    cost: usage.reduce(
      (total, entry) => ({
        input: total.input + entry.inputTokens + entry.cacheReadTokens + entry.cacheWriteTokens,
        output: total.output + entry.outputTokens,
      }),
      { input: 0, output: 0 },
    ),
  };
}

// ------------------------------------------------------------- helpers

const tool = (turn, name) => turn.tools.find((entry) => entry.name === name);
const has = (turn, kind) => turn.kinds.includes(kind);
const count = (turn, kind) => turn.kinds.filter((entry) => entry === kind).length;
const editors = (turn) => turn.components.filter((c) => EDITORS.has(c.component));
const deciders = (turn) => turn.components.filter((c) => DECIDERS.has(c.component) && c.action);
const text = (turn) =>
  turn.components
    .filter((c) => typeof c.text === 'string' || typeof c.label === 'string')
    .map((c) => c.text ?? c.label)
    .join(' | ');

/**
 * A specific-looking fare, which is what an invented price looks like.
 *
 * Comma-grouped thousands are the case to get right: "$3,500" begins with a
 * single digit, and a pattern demanding two in a row misses every four-figure
 * price — which is most of them.
 */
const quotesAPrice = (turn) =>
  /\$\s?\d[\d,.]*\d/.test(turn.prose) || has(turn, 'FlightOption');

// ------------------------------------------------------------- scenarios

const SCENARIOS = [
  {
    id: 'asks-before-pricing',
    why: 'The first version priced "a sample week in April" against dates nobody gave.',
    message: 'I want to fly to Madrid in April with my partner. Show me options.',
    checks: [
      ['it does not price anything yet', (t) => !quotesAPrice(t)],
      ['it asks for the dates', (t) => has(t, 'DateRangePicker') || has(t, 'DateTimeInput')],
      [
        'and everything else missing, in the same surface',
        (t) => editors(t).length >= 2,
        (t) => `${editors(t).length} editors: ${editors(t).map((c) => c.component).join(', ')}`,
      ],
      [
        'with exactly one button to send it',
        (t) => count(t, 'Button') === 1,
        (t) => `${count(t, 'Button')} buttons`,
      ],
      [
        'and no editor sends on its own',
        (t) => editors(t).every((c) => !c.action),
        (t) => editors(t).filter((c) => c.action).map((c) => c.component).join(', '),
      ],
      [
        'binding trip facts where the host pre-fills them',
        (t) =>
          editors(t).some((c) =>
            JSON.stringify(c).includes('"/trip/'),
          ),
        (t) => JSON.stringify(editors(t)[0] ?? {}).slice(0, 120),
      ],
    ],
  },

  {
    id: 'suggests-origin',
    why: 'Every trip used to depart from JFK, because that was the default.',
    message: 'I want to go to Madrid next month.',
    checks: [
      [
        // LAX is what America/Los_Angeles maps to. The check is that it used
        // the timezone at all rather than falling back to the old JFK default.
        'it offers a departure airport from the timezone, not JFK',
        (t) => {
          const drawn = JSON.stringify(t.components) + t.prose;
          return /\b(LAX|SFO|Los Angeles|San Francisco)\b/i.test(drawn) && !/\bJFK\b/.test(drawn);
        },
        (t) => text(t).slice(0, 140),
      ],
      ['it does not silently assume one', (t) => !quotesAPrice(t)],
    ],
  },

  {
    id: 'rough-is-allowed',
    why: 'Refusing to answer "roughly what does April cost" would be its own failure.',
    message: 'Roughly what would a week in Madrid cost in April, ballpark? I have no dates yet.',
    checks: [
      [
        'it answers rather than only asking',
        (t) => quotesAPrice(t) || /\$/.test(text(t)),
        (t) => t.prose.slice(0, 140),
      ],
      [
        'and says the figure is indicative',
        (t) => /indicative|rough|ballpark|approximate|estimate/i.test(t.prose + text(t)),
      ],
    ],
  },

  {
    id: 'prices-with-basis',
    why: 'A fare with no route, date or party size beside it reads as untrustworthy.',
    message: 'Show me the flights.',
    trip: { destination: 'Madrid', origin: 'SFO', startDate: '2027-04-12', endDate: '2027-04-19', travelers: 2 },
    checks: [
      ['it shows flights now that it can', (t) => has(t, 'FlightOption')],
      [
        'the surface says what it is priced against',
        (t) => /SFO/.test(text(t)) && /Madrid|MAD/.test(text(t)),
        (t) => text(t).slice(0, 160),
      ],
      ['the fares came from the tool, not from memory', (t) => Boolean(tool(t, 'search_flights'))],
      [
        'each flight is tappable, because picking is the answer',
        (t) => deciders(t).some((c) => c.component === 'FlightOption'),
      ],
    ],
  },

  {
    id: 'compiles',
    why: 'A block that does not compile leaves prose with a hole in it.',
    message:
      'Show me the three cheapest flights with all the details — airline, times, duration, ' +
      'stops, flight number, cabin and a badge on the best one.',
    trip: { destination: 'Madrid', origin: 'SFO', startDate: '2027-04-12', endDate: '2027-04-19', travelers: 2 },
    checks: [
      [
        'the surface compiled',
        (t) => t.errors.filter((e) => e.type === 'ui_error').length === 0,
        (t) => `${t.errors[0]?.message ?? ''} :: ${String(t.errors[0]?.express ?? '').slice(0, 200)}`,
      ],
      ['and something was drawn', (t) => t.components.length > 0],
      [
        'without needing the rewrite',
        (t) => !t.events.some((e) => e.type === 'retry'),
        (t) => t.events.find((e) => e.type === 'retry')?.reason ?? '',
      ],
    ],
  },

  {
    id: 'panel-is-read-only',
    why: 'The panel is the record. A control there is a control that does nothing.',
    surface: 'sidebar',
    message: 'Show me where the trip stands.',
    trip: {
      destination: 'Madrid',
      origin: 'SFO',
      startDate: '2027-04-12',
      endDate: '2027-04-19',
      travelers: 2,
      selectedFlight: 'IB614',
      flightPrice: 257,
    },
    checks: [
      ['it draws the panel', (t) => t.components.length > 0],
      [
        'with no editors at all',
        (t) => editors(t).length === 0,
        (t) => editors(t).map((c) => c.component).join(', '),
      ],
      [
        'and a Change on the decisions',
        (t) => count(t, 'Button') >= 1,
        (t) => `${count(t, 'Button')} buttons`,
      ],
      [
        'whose event asks to change a named field',
        (t) =>
          t.components.some(
            (c) => c.component === 'Button' && JSON.stringify(c.action ?? {}).includes('field'),
          ),
        (t) =>
          JSON.stringify(t.components.find((c) => c.component === 'Button')?.action ?? {}).slice(0, 140),
      ],
      [
        'and every button here is a Change, not a question',
        (t) =>
          t.components
            .filter((c) => c.component === 'Button')
            .every((c) => c.action?.event?.name === 'change'),
        (t) =>
          t.components
            .filter((c) => c.component === 'Button')
            .map((c) => c.action?.event?.name)
            .join(', '),
      ],
    ],
  },

  {
    id: 'multi-leg',
    why: 'One traveller out, two back. A single party size prices the return wrong.',
    message:
      'SFO to NYC with 1 stop in Chicago for 2 nights to attend a wedding, then back to SFO from NYC. ' +
      "Coming back it's 2 tickets, I'm travelling home with a friend.",
    checks: [
      ['it records the whole route in one go', (t) => (t.trip.legs ?? []).length >= 2],
      [
        'with a different party size on the leg that has one',
        (t) => (t.trip.legs ?? []).some((leg) => leg.travelers === 2),
        (t) => JSON.stringify(t.trip.legs ?? []).slice(0, 200),
      ],
      [
        'and it does not lose the wedding',
        (t) => /wedding/i.test(JSON.stringify(t.trip)),
      ],
      ['it still will not price without dates', (t) => !has(t, 'FlightOption')],
    ],
  },

  {
    id: 'rules-a-stage-out',
    why: 'A planner that keeps asking about a hotel you declined is a form.',
    message: "We're driving, no flights needed. And we're staying with my sister, so no hotel either.",
    trip: { destination: 'Monterey', origin: 'SFO', startDate: '2027-04-12', endDate: '2027-04-14', travelers: 2 },
    checks: [
      [
        'it records that flights do not apply',
        (t) => {
          const skip = t.trip.skip ?? [];
          const legs = t.trip.legs ?? [];
          return skip.includes('flight') || legs.some((leg) => leg.needsStay === false);
        },
        (t) => JSON.stringify({ skip: t.trip.skip, legs: t.trip.legs }).slice(0, 200),
      ],
      ['and does not go looking for flights anyway', (t) => !tool(t, 'search_flights')],
      ['and does not draw flight cards', (t) => !has(t, 'FlightOption')],
    ],
  },

  {
    id: 'finishes',
    why: 'A planner has to know when to stop asking.',
    message: 'Anything else?',
    trip: {
      destination: 'Madrid',
      origin: 'SFO',
      startDate: '2027-04-12',
      endDate: '2027-04-19',
      travelers: 2,
      selectedFlight: 'IB614',
      flightPrice: 257,
      selectedHotel: 'h_MAD_0',
      nightlyPrice: 180,
      budget: 2600,
      planned: true,
    },
    checks: [
      [
        'it wishes them a good trip rather than inventing a question',
        (t) => /good trip|great trip|have a wonderful|enjoy/i.test(t.prose + text(t)),
        (t) => t.prose.slice(-160),
      ],
      [
        'and offers what is actually left',
        (t) => /shar|activit|add.*day|more to the day/i.test(t.prose + text(t)),
        (t) => t.prose.slice(0, 160),
      ],
    ],
  },

  {
    id: 'no-invented-places',
    why: 'A fabricated guide is worse than an honest "I do not know that one".',
    message: 'Plan me three days in Zubrowka.',
    checks: [
      [
        'it says the place is not real rather than inventing a guide',
        (t) =>
          /don'?t have|no (detailed )?guide|not.*know|fiction|invent|imagin|made up|isn'?t (a )?real/i.test(
            t.prose,
          ),
        (t) => t.prose.slice(0, 160),
      ],
      ['and does not invent an itinerary for it', (t) => !has(t, 'ItineraryDay')],
    ],
  },
];

// ------------------------------------------------------------------ running

const wanted = ONLY ? SCENARIOS.filter((s) => s.id.includes(ONLY)) : SCENARIOS;
if (wanted.length === 0) {
  console.error(`No scenario matches "${ONLY}". Known: ${SCENARIOS.map((s) => s.id).join(', ')}`);
  process.exit(2);
}

console.log(`Live evaluation · ${MODEL} · ${BASE}`);
console.log(`${wanted.length} scenario(s), real turns, real money.\n`);

const report = [];
let passed = 0;
let failed = 0;
const total = { input: 0, output: 0 };

for (const scenario of wanted) {
  process.stdout.write(`${scenario.id}\n  ${scenario.why}\n`);

  let observed;
  try {
    observed = await turn({
      message: scenario.message,
      surface: scenario.surface,
      trip: scenario.trip,
      session: `eval-${scenario.id}-${Date.now()}`,
    });
  } catch (error) {
    console.log(`  ✗ the turn itself failed — ${error.message}\n`);
    failed += 1;
    report.push({ id: scenario.id, error: error.message });
    continue;
  }

  total.input += observed.cost.input;
  total.output += observed.cost.output;

  const results = [];
  for (const [label, test, detail] of scenario.checks) {
    let ok = false;
    try {
      ok = Boolean(test(observed));
    } catch (error) {
      ok = false;
    }
    const note = ok ? '' : detail ? ` — ${String(detail(observed) ?? '').replace(/\s+/g, ' ').slice(0, 150)}` : '';
    console.log(`  ${ok ? '✓' : '✗'} ${label}${note}`);
    results.push({ label, ok });
    if (ok) passed += 1;
    else failed += 1;
  }

  if (observed.errors.length > 0) {
    console.log(`  ! ${observed.errors.length} error event(s): ${observed.errors[0].message?.slice(0, 100)}`);
  }

  report.push({
    id: scenario.id,
    checks: results,
    tools: observed.tools.map((entry) => entry.name),
    components: observed.kinds,
    prose: observed.prose.slice(0, 500),
    trip: observed.trip,
    cost: observed.cost,
  });
  console.log('');
}

// Opus 5 list price, so the number is a real number rather than a token count.
const dollars = (total.input / 1e6) * 5 + (total.output / 1e6) * 25;
console.log(`${passed}/${passed + failed} checks passed`);
console.log(
  `${(total.input / 1000).toFixed(1)}k in / ${(total.output / 1000).toFixed(1)}k out · ~$${dollars.toFixed(2)}`,
);

if (JSON_OUT) {
  const { writeFileSync } = await import('node:fs');
  writeFileSync(JSON_OUT, JSON.stringify({ model: MODEL, passed, failed, report }, null, 2));
  console.log(`\n→ ${JSON_OUT}`);
}

process.exit(failed === 0 ? 0 : 1);
