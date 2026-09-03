/**
 * The agent's tools.
 *
 * A deliberate split runs through this file, and it is the whole architectural
 * idea of the project:
 *
 *   **Tools return data. The skill turns data into UI.**
 *
 * No tool here returns A2UI. `search_flights` returns flights. The model reads
 * them and writes Express, because deciding *how* to present five flights —
 * which to lead with, what to say about the stopover, whether this is a moment
 * for a price summary — is a judgement call, and judgement is the thing the
 * model is for. A tool that returned pre-rendered cards would move that
 * decision into this file, where it would be frozen and wrong half the time.
 *
 * The one exception is `save_trip`, which writes rather than reads, because the
 * user's choices have to outlive the turn that made them.
 */

import type Anthropic from '@anthropic-ai/sdk';

import {
  askFor,
  basisOf,
  bindingFor,
  merge as mergeTrip,
  missingFor,
  nights,
  normalize as normalizeTrip,
  problems,
  summarize,
  type Trip,
  type TripKey,
} from '@travel-a2ui/trip';

import {
  estimateTrip,
  getWeather,
  knownDestinations,
  resolveDestination,
  searchFlights,
  searchHotels,
} from './travel.js';

export interface ToolContext {
  /** The trip state so far, readable and writable across turns. */
  trip: Record<string, unknown>;
  saveTrip(patch: Record<string, unknown>): void;
}

export const TOOLS: Anthropic.Tool[] = [
  {
    name: 'search_flights',
    description:
      'Finds flights to a destination. Returns fare, timing and stop data — not UI. ' +
      'Call it before showing flight options so the numbers on screen are real. ' +
      'Needs a date: with none given and none saved on the trip, it returns a request to ' +
      'ask the traveler rather than pricing a week nobody chose. Set flexible only when ' +
      'they explicitly asked for a rough or seasonal figure.',
    input_schema: {
      type: 'object',
      properties: {
        destination: {
          type: 'string',
          description: "Where the traveler is going: a city name or airport code, e.g. 'Madrid' or 'MAD'.",
        },
        origin: { type: 'string', description: "Departure airport code. Defaults to 'JFK'." },
        date: { type: 'string', description: 'Outbound date as YYYY-MM-DD.' },
        travelers: { type: 'integer', description: 'Number of travelers.' },
        cabin: { type: 'string', enum: ['economy', 'premium', 'business', 'first'] },
        maxPrice: { type: 'number', description: 'Highest acceptable per-traveler fare.' },
        nonstopOnly: { type: 'boolean', description: 'Exclude itineraries with a stop.' },
        flexible: {
          type: 'boolean',
          description:
            'Only when the traveler asked for a rough or seasonal figure rather than their trip. ' +
            'Prices an indicative date, which you must then label as indicative on screen.',
        },
      },
      required: ['destination'],
      additionalProperties: false,
    },
    strict: true,
  },
  {
    name: 'search_hotels',
    description:
      'Finds places to stay. Returns nightly rates, neighbourhoods, ratings and amenities — not UI.',
    input_schema: {
      type: 'object',
      properties: {
        destination: { type: 'string', description: 'City name or airport code.' },
        nights: { type: 'integer', description: 'Length of stay in nights.' },
        travelers: { type: 'integer' },
        maxNightly: { type: 'number', description: 'Highest acceptable nightly rate.' },
        neighborhood: { type: 'string', description: 'Preferred area, if the traveler named one.' },
        flexible: { type: 'boolean', description: 'Only for an explicitly rough figure. See search_flights.' },
      },
      required: ['destination'],
      additionalProperties: false,
    },
    strict: true,
  },
  {
    name: 'get_destination',
    description:
      'Returns what is worth doing in a destination, when to go, and the local currency. ' +
      "Call it before writing an itinerary so the day plan names real places. With no argument, lists every destination this agent knows.",
    input_schema: {
      type: 'object',
      properties: {
        destination: { type: 'string', description: 'City name or airport code. Omit to list all.' },
      },
      required: [],
      additionalProperties: false,
    },
  },
  {
    name: 'get_weather',
    description: 'Returns a short forecast for a destination — highs, lows and conditions by day.',
    input_schema: {
      type: 'object',
      properties: {
        destination: { type: 'string' },
        startDate: { type: 'string', description: 'First day of the forecast, YYYY-MM-DD.' },
        days: { type: 'integer', description: 'How many days, up to 7.' },
      },
      required: ['destination'],
      additionalProperties: false,
    },
    strict: true,
  },
  {
    name: 'estimate_cost',
    description:
      'Breaks a trip into itemised costs and a total. Pass the chosen fare and nightly rate when ' +
      'the traveler has picked them, so the estimate reflects their actual trip rather than an average. ' +
      'Needs dates and party size, from the arguments or the saved trip; without them it returns a ' +
      'request to ask instead of a total that means nothing.',
    input_schema: {
      type: 'object',
      properties: {
        destination: { type: 'string' },
        travelers: { type: 'integer' },
        nights: { type: 'integer' },
        flightPrice: { type: 'number', description: 'Chosen per-traveler fare, if any.' },
        nightlyPrice: { type: 'number', description: 'Chosen nightly rate, if any.' },
        flexible: { type: 'boolean', description: 'Only for an explicitly rough figure. See search_flights.' },
      },
      required: ['destination'],
      additionalProperties: false,
    },
    strict: true,
  },
  {
    name: 'save_trip',
    description:
      "Records what the traveler has decided — destination, dates, party size, the flight and stay they " +
      'picked, their budget. Call it as soon as something is settled: later turns and the other surfaces ' +
      'read this, and anything not saved here is forgotten when the turn ends. Also how a trip is told ' +
      'it does not need a stage (skip) and how a multi-city trip is held (legs). Returns what is still ' +
      'needed, so the reply tells you what to do next.',
    input_schema: {
      type: 'object',
      properties: {
        destination: { type: 'string' },
        startDate: { type: 'string', description: 'YYYY-MM-DD.' },
        endDate: { type: 'string', description: 'YYYY-MM-DD.' },
        travelers: { type: 'integer' },
        budget: { type: 'number' },
        selectedFlight: { type: 'string', description: 'Flight id the traveler chose.' },
        flightPrice: { type: 'number', description: 'Per-traveler fare of that flight.' },
        selectedHotel: { type: 'string', description: 'Hotel id the traveler chose.' },
        nightlyPrice: { type: 'number', description: 'Nightly rate of that stay.' },
        cabin: { type: 'string', enum: ['economy', 'premium', 'business', 'first'] },
        nonstopOnly: { type: 'boolean' },
        neighborhood: { type: 'string' },
        spent: { type: 'number', description: 'What is actually committed, not estimated.' },
        planned: {
          type: 'boolean',
          description: 'True once the day-by-day plan is drawn and the traveler is happy with it.',
        },
        skip: {
          type: 'array',
          items: { type: 'string', enum: ['route', 'dates', 'party', 'flight', 'stay', 'budget', 'plan'] },
          description:
            'Stages this trip does not need — driving rather than flying, staying with family, ' +
            'no fixed budget. A skipped stage counts as settled and is never asked about again. ' +
            'Record it the moment the traveler rules something out.',
        },
        legs: {
          type: 'array',
          description:
            'Stops after the first, each with its own dates. This is how a multi-city trip is ' +
            'held; the top-level fields describe the first leg.',
          items: {
            type: 'object',
            properties: {
              destination: { type: 'string' },
              startDate: { type: 'string', description: 'YYYY-MM-DD.' },
              endDate: { type: 'string', description: 'YYYY-MM-DD.' },
              origin: { type: 'string', description: 'Departure airport for this leg, if it differs.' },
              notes: { type: 'string' },
            },
            required: ['destination'],
          },
        },
        notes: { type: 'string', description: 'Anything else worth remembering, in one line.' },
      },
      required: [],
      additionalProperties: false,
    },
  },
  {
    name: 'get_trip',
    description: 'Reads back everything recorded about this trip so far.',
    input_schema: { type: 'object', properties: {}, required: [], additionalProperties: false },
  },
];

type ToolInput = Record<string, unknown>;

const str = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback;
const num = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isFinite(value) ? value : undefined;

/**
 * What to answer when a tool was asked to price a trip with no dates.
 *
 * A prompt rule saying "ask first" is a suggestion; a model in a hurry prices
 * a plausible week and calls it a sample, and the traveler ends up looking at
 * fares for a date they never chose. This is the same rule expressed where the
 * model cannot talk past it: no dates, no prices — here is what to draw instead.
 *
 * `flexible: true` is the deliberate way through, for "roughly what does Madrid
 * cost in April". The result is then labelled indicative, so what is on screen
 * still says what it is.
 */
function needsInput(what: string, missing: readonly TripKey[]): {
  result: unknown;
  isError: boolean;
} {
  return {
    result: {
      needs: missing,
      message:
        `Cannot ${what} without ${askFor(missing)}, and inventing a plausible answer is ` +
        'worse than asking. Draw the controls for all of it in one surface — bound to ' +
        `${missing.map((key) => `$${bindingFor(key)}`).join(', ')} so the host pre-fills ` +
        'them — with a single commit button, and wait. If the traveler explicitly asked ' +
        'for a rough or seasonal figure, call again with flexible: true and label what ' +
        'you draw as indicative.',
    },
    isError: false,
  };
}

/**
 * The trip a tool should reason about: what is saved, plus what this call says.
 *
 * A model that passes `date` explicitly is describing the same trip as one that
 * relies on the saved `startDate`, and neither should be handled specially.
 */
function effectiveTrip(input: ToolInput, context: ToolContext): Trip {
  return mergeTrip(normalizeTrip(context.trip), {
    destination: input['destination'],
    origin: input['origin'],
    startDate: input['date'] ?? input['startDate'],
    endDate: input['endDate'],
    travelers: input['travelers'],
    cabin: input['cabin'],
    maxFare: input['maxPrice'],
    maxNightly: input['maxNightly'],
    neighborhood: input['neighborhood'],
  });
}

/** Runs one tool call. Never throws: a thrown tool is a dead turn. */
export async function runTool(
  name: string,
  input: ToolInput,
  context: ToolContext,
): Promise<{ result: unknown; isError: boolean }> {
  try {
    switch (name) {
      case 'search_flights': {
        const trip = effectiveTrip(input, context);
        const missing = missingFor(trip, 'priceFlights');
        if (missing.length > 0 && input['flexible'] !== true) {
          return needsInput('price flights', missing);
        }

        const found = searchFlights({
          destination: trip.destination ?? str(input['destination']),
          origin: trip.origin,
          date: trip.startDate,
          travelers: trip.travelers,
          cabin: trip.cabin,
          maxPrice: trip.maxFare,
          nonstopOnly: input['nonstopOnly'] === true || trip.nonstopOnly === true,
        });

        // Echoed back so the surface can say what it is showing. A price with
        // nothing beside it is the thing that made this untrustworthy.
        return {
          result: {
            ...found,
            searchedFor: {
              basis: basisOf(trip),
              date: trip.startDate ?? null,
              origin: trip.origin ?? null,
              travelers: trip.travelers ?? null,
              cabin: trip.cabin ?? 'economy',
              indicative: missing.length > 0,
            },
          },
          isError: false,
        };
      }

      case 'search_hotels': {
        const trip = effectiveTrip(input, context);
        const missing = missingFor(trip, 'priceStay');
        const stayNights = num(input['nights']) ?? nights(trip);
        if (missing.length > 0 && stayNights === undefined && input['flexible'] !== true) {
          return needsInput('price a stay', missing);
        }
        const found = searchHotels({
          destination: trip.destination ?? str(input['destination']),
          nights: stayNights,
          travelers: trip.travelers,
          maxNightly: trip.maxNightly,
          neighborhood: trip.neighborhood,
        });
        return {
          result: {
            ...found,
            searchedFor: {
              basis: basisOf(trip),
              nights: stayNights ?? null,
              travelers: trip.travelers ?? null,
              checkIn: trip.startDate ?? null,
              indicative: stayNights === undefined,
            },
          },
          isError: false,
        };
      }

      case 'get_destination': {
        const query = str(input['destination']);
        if (!query) return { result: { destinations: knownDestinations() }, isError: false };
        const destination = resolveDestination(query);
        if (!destination) {
          // A miss is not an error — it is information the model can act on,
          // and naming the alternatives is what turns it into a next step.
          return {
            result: {
              found: false,
              message: `No detailed guide for '${query}'.`,
              available: knownDestinations().map((entry) => entry.city),
            },
            isError: false,
          };
        }
        return { result: { found: true, ...destination }, isError: false };
      }

      case 'get_weather':
        return {
          result: getWeather(str(input['destination']), str(input['startDate']) || undefined, num(input['days']) ?? 5),
          isError: false,
        };

      case 'estimate_cost': {
        const trip = effectiveTrip(input, context);
        const missing = missingFor(trip, 'totalTrip');
        const stayNights = num(input['nights']) ?? nights(trip);
        if (missing.length > 0 && input['flexible'] !== true) {
          return needsInput('total up a trip', missing);
        }
        const estimate = estimateTrip({
          destination: trip.destination ?? str(input['destination']),
          travelers: trip.travelers,
          nights: stayNights,
          flightPrice: num(input['flightPrice']) ?? trip.flightPrice,
          nightlyPrice: num(input['nightlyPrice']) ?? trip.nightlyPrice,
        });
        return {
          result: {
            ...estimate,
            // The caption the surface should carry. A total is meaningless
            // without the party size and length it totals.
            basis: {
              summary: basisOf(trip),
              nights: stayNights ?? null,
              travelers: trip.travelers ?? null,
              startDate: trip.startDate ?? null,
              endDate: trip.endDate ?? null,
              indicative: missing.length > 0,
            },
          },
          isError: false,
        };
      }

      case 'save_trip': {
        // Normalised on the way in, so what is stored is in the trip's own
        // shapes rather than whatever the model happened to type.
        const next = mergeTrip(normalizeTrip(context.trip), input);
        const today = new Date().toISOString().slice(0, 10);
        const wrong = problems(next, today);

        // Refused rather than recorded: everything downstream prices against
        // these, and a range that ends before it starts produces numbers that
        // look authoritative and are not. An over-budget trip is a real state,
        // not a mistake, so it is reported and saved.
        const blocking = wrong.filter((problem) => problem.field !== 'spent');
        if (blocking.length > 0) {
          return {
            result: {
              saved: false,
              problems: blocking,
              message: `Not saved: ${blocking.map((p) => p.message).join(' ')} Ask the traveler to confirm.`,
            },
            isError: true,
          };
        }

        context.saveTrip(normalizeTrip(input));
        const saved = mergeTrip(normalizeTrip(context.trip), {});
        return {
          result: {
            saved: true,
            trip: saved,
            stillNeeded: summarize(saved, today).missing,
            ...(wrong.length > 0 ? { warnings: wrong } : {}),
          },
          isError: false,
        };
      }

      case 'get_trip':
        return { result: { trip: context.trip }, isError: false };

      default:
        return { result: { error: `Unknown tool '${name}'.` }, isError: true };
    }
  } catch (error) {
    return {
      result: { error: error instanceof Error ? error.message : String(error) },
      isError: true,
    };
  }
}
