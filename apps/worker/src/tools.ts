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
      'Call it before showing flight options so the numbers on screen are real.',
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
      'the traveler has picked them, so the estimate reflects their actual trip rather than an average.',
    input_schema: {
      type: 'object',
      properties: {
        destination: { type: 'string' },
        travelers: { type: 'integer' },
        nights: { type: 'integer' },
        flightPrice: { type: 'number', description: 'Chosen per-traveler fare, if any.' },
        nightlyPrice: { type: 'number', description: 'Chosen nightly rate, if any.' },
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
      'read this, and anything not saved here is forgotten when the turn ends.',
    input_schema: {
      type: 'object',
      properties: {
        destination: { type: 'string' },
        startDate: { type: 'string', description: 'YYYY-MM-DD.' },
        endDate: { type: 'string', description: 'YYYY-MM-DD.' },
        travelers: { type: 'integer' },
        budget: { type: 'number' },
        selectedFlight: { type: 'string', description: 'Flight id the traveler chose.' },
        selectedHotel: { type: 'string', description: 'Hotel id the traveler chose.' },
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

/** Runs one tool call. Never throws: a thrown tool is a dead turn. */
export async function runTool(
  name: string,
  input: ToolInput,
  context: ToolContext,
): Promise<{ result: unknown; isError: boolean }> {
  try {
    switch (name) {
      case 'search_flights':
        return {
          result: searchFlights({
            destination: str(input['destination']),
            origin: str(input['origin']) || undefined,
            date: str(input['date']) || undefined,
            travelers: num(input['travelers']),
            cabin: str(input['cabin']) || undefined,
            maxPrice: num(input['maxPrice']),
            nonstopOnly: input['nonstopOnly'] === true,
          }),
          isError: false,
        };

      case 'search_hotels':
        return {
          result: searchHotels({
            destination: str(input['destination']),
            nights: num(input['nights']),
            travelers: num(input['travelers']),
            maxNightly: num(input['maxNightly']),
            neighborhood: str(input['neighborhood']) || undefined,
          }),
          isError: false,
        };

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

      case 'estimate_cost':
        return {
          result: estimateTrip({
            destination: str(input['destination']),
            travelers: num(input['travelers']),
            nights: num(input['nights']),
            flightPrice: num(input['flightPrice']),
            nightlyPrice: num(input['nightlyPrice']),
          }),
          isError: false,
        };

      case 'save_trip': {
        const patch: Record<string, unknown> = {};
        for (const [key, value] of Object.entries(input)) {
          if (value !== undefined && value !== null && value !== '') patch[key] = value;
        }
        context.saveTrip(patch);
        return { result: { saved: true, trip: context.trip }, isError: false };
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
