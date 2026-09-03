/**
 * The MCP app: travel tools whose results are user interfaces.
 *
 * This is the fourth modality, and the one that reaches furthest. Everything
 * else here renders A2UI inside *our* app. An MCP server renders it inside
 * someone else's — Claude, Codex, any host that speaks the protocol — because
 * the tool result carries an A2UI payload instead of a wall of text.
 *
 * Two kinds of tool, and the difference matters:
 *
 *   - **Composed tools** (`show_flight_options`, `show_trip_dashboard`, …) take
 *     structured arguments and return a surface built from the travel catalog.
 *     The host's model decides *what* to show; this server decides how. Fast,
 *     deterministic, no second model in the path.
 *   - **`render_a2ui_express`** takes Express the host's model wrote itself and
 *     compiles it. That is what makes the layouts genuinely generative rather
 *     than a fixed menu of five cards — and the `a2ui-express` prompt, served
 *     from the same generated skill this project uses everywhere else, is how
 *     the host's model learns to write it.
 *
 * Transport is stateless Streamable HTTP: every POST is self-contained, which
 * is all a Worker wants to be, and it means no session affinity to arrange.
 *
 * ## Two ways to hand over a surface
 *
 * Every tool result carries the A2UI payload, which is small and is what a host
 * with its own A2UI renderer wants. Most hosts today do not have one, so the
 * result *also* carries the surface as a `text/html` resource the host renders
 * in an iframe.
 *
 * That HTML is a **shell**, under a kilobyte: the payload inlined, and a script
 * tag pointing back at this deployment for the renderer itself. The renderer is
 * the same React component library the web app uses — around 230 kB — and it is
 * fetched once and cached, rather than riding along on every tool call and
 * eating the host's result budget each time.
 *
 * The payload stays inlined because it is the only part that varies and it is
 * small, so the surface has everything it needs the moment the script boots.
 * Neither is read by the model: the text summary in the same result is what the
 * model sees. A host that renders A2UI natively can drop the HTML entirely with
 * `POST /mcp?view=payload`.
 */

import { ExpressCompiler, type A2uiMessage } from '@travel-a2ui/express';

import {
  askFor,
  basisOf,
  bindingFor,
  missingFor,
  nights,
  normalize as normalizeTrip,
  type Trip,
  type TripKey,
} from '@travel-a2ui/trip';

import { CATALOG, CATALOG_ID } from './agent.js';
import { estimateTrip, getWeather, resolveDestination, searchFlights, searchHotels } from './travel.js';
import skillExpress from '../../../skills/express-monolithic/a2ui/SKILL.md';
import viewShell from '../../mcp-view/shell.html';

const PROTOCOL_VERSION = '2025-06-18';
const SERVER_INFO = { name: 'travel-a2ui', title: 'Travel A2UI', version: '0.1.0' };

/**
 * The MIME type an A2UI payload travels under.
 *
 * A host that understands it renders the surface; one that does not still gets
 * the text summary in the same result and loses nothing but the pictures. That
 * degradation is deliberate — an MCP tool that is useless in a plain host is a
 * bad MCP tool.
 */
const A2UI_MIME = 'application/vnd.a2ui+json';

/** What a tool result carries: the payload, the rendered view, or both. */
export type ViewMode = 'payload' | 'html' | 'both';

/** Everything about a request that changes what a tool result looks like. */
export interface RenderContext {
  view: ViewMode;
  /** Absolute origin the shell loads the renderer from. No trailing slash. */
  origin: string;
}

const compiler = new ExpressCompiler(CATALOG, 'v0.9.1');

/**
 * Fills in the shell: the surface, and where to find the renderer.
 *
 * The payload placeholder sits inside a `<script type="application/json">`,
 * where the only sequence that can end the block early is `</script`. Escaping
 * it is the whole of the safety story, and it is why the payload goes in a JSON
 * script block rather than into a JS string literal.
 *
 * The origin comes from the URL the host just called, so a production deploy, a
 * preview and `wrangler dev` each serve their own renderer with nothing
 * configured anywhere.
 */
function renderView(
  surfaceId: string,
  messages: A2uiMessage[],
  summary: string,
  origin: string,
): string {
  const payload = JSON.stringify({ surfaceId, messages, summary }).replaceAll(
    '</script',
    '<\\/script',
  );
  return viewShell.replaceAll('__ORIGIN__', origin).replace('__A2UI_PAYLOAD__', payload);
}

interface JsonRpcRequest {
  jsonrpc: '2.0';
  id?: string | number | null;
  method: string;
  params?: Record<string, unknown>;
}

const ok = (id: unknown, result: unknown) => ({ jsonrpc: '2.0' as const, id, result });
const err = (id: unknown, code: number, message: string) => ({
  jsonrpc: '2.0' as const,
  id,
  error: { code, message },
});

/** Quotes a string for Express source. */
const q = (value: unknown): string =>
  JSON.stringify(String(value ?? '')).replace(/\\u/g, '\\\\u');

const str = (value: unknown, fallback = ''): string => (typeof value === 'string' ? value : fallback);
const int = (value: unknown, fallback: number): number =>
  typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : fallback;

interface Surface {
  express: string;
  summary: string;
  surfaceId: string;
}

/**
 * Raised when a tool was asked to price a trip nobody has described.
 *
 * The same rule the web app enforces, for the same reason: a fare for a week
 * the traveler never chose looks exactly like a fare for one they did. Here it
 * is a tool error naming what is missing, which the host's model can act on —
 * by asking, or by calling again with `flexible: true` for a rough figure.
 */
class NeedsInput extends Error {
  constructor(missing: readonly TripKey[], what: string) {
    super(
      `Cannot ${what} without ${askFor(missing)}. Ask the traveler — draw the controls for ` +
        `all of it in one surface with render_a2ui_express, bound to ` +
        `${missing.map((key) => `$${bindingFor(key)}`).join(', ')} with a single commit ` +
        'button — or pass the values as arguments. For a deliberately rough figure, call ' +
        'again with flexible: true and say on screen that it is indicative.',
    );
  }
}

/**
 * The trip a tool call describes.
 *
 * The MCP server is stateless, so the host's arguments *are* the trip. Running
 * them through the same model the web app uses means a date arrives in one
 * shape, a cabin picked from a list is a string rather than a one-item array,
 * and "can this be priced yet" has the same answer in both places.
 */
function tripOf(args: Record<string, unknown>): Trip {
  return normalizeTrip({
    destination: args['destination'],
    origin: args['origin'],
    startDate: args['date'] ?? args['startDate'],
    endDate: args['endDate'],
    travelers: args['travelers'],
    cabin: args['cabin'],
    maxFare: args['maxPrice'],
    maxNightly: args['maxNightly'],
    neighborhood: args['neighborhood'],
    budget: args['budget'],
    spent: args['spent'],
  });
}

type Flow = 'inline' | 'sidebar' | 'home';

function flowOf(args: Record<string, unknown>): Flow {
  const value = str(args['surface']);
  return value === 'sidebar' || value === 'home' ? value : 'inline';
}

/**
 * The surface id a flow writes to.
 *
 * `sidebar` and `home` are *singular*: writing to them again replaces the panel,
 * which is what makes them panels rather than a feed. Inline surfaces are keyed
 * by what they show, so two different questions get two different cards.
 */
function surfaceIdFor(flow: Flow, inlineId: string): string {
  return flow === 'inline' ? inlineId : `mcp-${flow}`;
}

/**
 * How many options a flow has room for.
 *
 * Not a style preference: a sidebar column is narrow and a home screen is a
 * summary, so the same six flights that read well inline read as a wall in
 * either. The model chose the flow; this honours it.
 */
function limitFor(flow: Flow): number {
  return flow === 'home' ? 2 : flow === 'sidebar' ? 3 : 4;
}

/**
 * The three flows, as an argument.
 *
 * A host that installs this plugin gets the same three placements the app has,
 * because they are properties of *where the answer goes*, not of this codebase:
 *
 *   inline   — attached to the message being answered. One job, a handful of
 *              components, an action that continues the conversation.
 *   sidebar  — a panel that persists beside the conversation and holds the
 *              controls for the trip as a whole. Replaced, never appended.
 *   home     — a summary of where the trip stands, read first and not in reply
 *              to anything.
 *
 * The same data composes differently for each: inline shows three flights,
 * sidebar shows the filters that produced them, home shows that a flight is
 * still unbooked. Tools take `surface` so the host can say which it wants.
 */
const SURFACE_ARG = {
  type: 'string',
  enum: ['inline', 'sidebar', 'home'],
  description:
    "Where this surface will be placed. 'inline' (default) answers the current message; " +
    "'sidebar' is a persistent panel of controls; 'home' is a standing summary. " +
    'It changes what is composed, not just where it goes.',
} as const;

const TOOLS = [
  {
    name: 'show_flight_options',
    title: 'Show flight options',
    description:
      'Searches flights and returns them as an interactive A2UI surface the user can pick from, ' +
      'instead of a list of text. Use whenever the user is choosing a flight.',
    inputSchema: {
      type: 'object',
      properties: {
        destination: { type: 'string', description: 'City name or airport code.' },
        origin: { type: 'string', description: 'Departure airport code. Defaults to JFK.' },
        date: { type: 'string', description: 'Outbound date, YYYY-MM-DD.' },
        travelers: { type: 'integer' },
        cabin: { type: 'string', enum: ['economy', 'premium', 'business', 'first'] },
        maxPrice: { type: 'number' },
        nonstopOnly: { type: 'boolean' },
        surface: SURFACE_ARG,
      },
      required: ['destination'],
    },
  },
  {
    name: 'show_hotel_options',
    title: 'Show places to stay',
    description:
      'Searches stays and returns them as A2UI hotel cards with rating, neighbourhood and nightly rate.',
    inputSchema: {
      type: 'object',
      properties: {
        destination: { type: 'string' },
        nights: { type: 'integer' },
        travelers: { type: 'integer' },
        maxNightly: { type: 'number' },
        neighborhood: { type: 'string' },
        surface: SURFACE_ARG,
      },
      required: ['destination'],
    },
  },
  {
    name: 'show_trip_controls',
    title: 'Show trip controls (sidebar)',
    description:
      'Returns the sidebar flow: a panel of controls for the trip as a whole — dates, party size, ' +
      'budget, stop preference — with one commit action. Use it when the user wants to *adjust* the ' +
      'trip rather than discuss it. The panel replaces itself each time; it is not a feed.',
    inputSchema: {
      type: 'object',
      properties: {
        destination: { type: 'string' },
        startDate: { type: 'string', description: 'Current start date, YYYY-MM-DD.' },
        endDate: { type: 'string', description: 'Current end date, YYYY-MM-DD.' },
        travelers: { type: 'integer' },
        maxPrice: { type: 'number', description: 'Current fare cap.' },
        nonstopOnly: { type: 'boolean' },
      },
      required: [],
    },
  },
  {
    name: 'show_itinerary',
    title: 'Show a day-by-day itinerary',
    description:
      'Builds a day-by-day plan for a destination from its real highlights and returns it as an ' +
      'A2UI itinerary the user can tap through.',
    inputSchema: {
      type: 'object',
      properties: {
        destination: { type: 'string' },
        days: { type: 'integer', description: 'How many days to plan, 1–7.' },
        startDate: { type: 'string', description: 'First day, YYYY-MM-DD.' },
        surface: SURFACE_ARG,
      },
      required: ['destination'],
    },
  },
  {
    name: 'show_trip_dashboard',
    title: 'Show a trip dashboard',
    description:
      'Returns a generated dashboard for a trip: days remaining, budget used, forecast and a map ' +
      'of what is planned. Use for "how is my trip looking" questions.',
    inputSchema: {
      type: 'object',
      properties: {
        destination: { type: 'string' },
        startDate: { type: 'string', description: 'Departure date, YYYY-MM-DD.' },
        travelers: { type: 'integer' },
        nights: { type: 'integer' },
        budget: { type: 'number' },
        spent: { type: 'number' },
      },
      required: ['destination'],
    },
  },
  {
    name: 'show_price_summary',
    title: 'Show what a trip costs',
    description: 'Returns an itemised cost breakdown and total as an A2UI price summary.',
    inputSchema: {
      type: 'object',
      properties: {
        destination: { type: 'string' },
        travelers: { type: 'integer' },
        nights: { type: 'integer' },
        flightPrice: { type: 'number' },
        nightlyPrice: { type: 'number' },
        surface: SURFACE_ARG,
      },
      required: ['destination'],
    },
  },
  {
    name: 'get_a2ui_component_reference',
    title: 'Read the component catalog',
    description:
      'Returns the full A2UI Express output contract: the grammar, the streaming rules, and the ' +
      'positional signature of every component and function in the travel catalog — flight and ' +
      'hotel cards, itinerary days, maps, price summaries, stat tiles, sliders, pickers, and the ' +
      'layout primitives. Call this once before render_a2ui_express, then compose whatever ' +
      'interface the conversation actually needs. Costs one call and makes every layout possible ' +
      'rather than the six this server hard-codes.',
    inputSchema: { type: 'object', properties: {}, required: [] },
  },
  {
    name: 'render_a2ui_express',
    title: 'Compose a custom interface',
    description:
      'Compiles A2UI Express you have written into a live interface, rendered by the same React ' +
      'component library as every other tool here. This is the general case and the other tools ' +
      'are shortcuts: use it whenever the layout you want is not one of them — a comparison table ' +
      'of three hotels next to a budget meter, a packing checklist, a single decision card. Call ' +
      'get_a2ui_component_reference first for the grammar and the signatures. Compile errors come ' +
      'back naming exactly what was wrong, so a second attempt can fix it.',
    inputSchema: {
      type: 'object',
      properties: {
        source: {
          type: 'string',
          description:
            'A2UI Express source. Declare components in order and finish with `root = …`; ' +
            'sentinel tags are optional, the compiler strips them.',
        },
        surfaceId: { type: 'string', description: 'Surface id to draw into. Defaults to "mcp".' },
      },
      required: ['source'],
    },
  },
] as const;

const RESOURCES = [
  {
    uri: 'a2ui://catalog/travel',
    name: 'Travel component catalog',
    title: 'A2UI travel catalog',
    description:
      'The JSON Schema catalog of every component these tools can render — the vocabulary available ' +
      'to render_a2ui_express.',
    mimeType: 'application/json',
  },
  {
    uri: 'a2ui://skill/express',
    name: 'A2UI Express skill',
    title: 'How to write A2UI Express',
    description:
      'The full output contract: grammar, streaming rules, and positional signatures for every ' +
      'component and function in the travel catalog.',
    mimeType: 'text/markdown',
  },
] as const;

const PROMPTS = [
  {
    name: 'a2ui-express',
    title: 'Write A2UI Express',
    description:
      'Loads the A2UI Express output contract and the travel catalog signatures, so you can compose ' +
      'your own interfaces and render them with render_a2ui_express.',
    arguments: [],
  },
] as const;

export async function handleMcp(request: Request): Promise<Response> {
  const url = new URL(request.url);

  // Chosen once, at install time, by whoever knows what their host can render.
  const requested = url.searchParams.get('view');
  const view: ViewMode =
    requested === 'payload' || requested === 'html' || requested === 'both' ? requested : 'both';

  // Normally the origin the host just called is the right one to load the
  // renderer from. `?origin=` covers the case where it is not — a tunnel, a
  // proxy, a preview URL that differs from the public one.
  const context: RenderContext = { view, origin: rendererOrigin(url) };

  if (request.method === 'GET') {
    // Streamable HTTP allows a server to decline the SSE channel. This one is
    // stateless, so there is nothing to push.
    return new Response('This MCP server is stateless: POST JSON-RPC to this endpoint.', {
      status: 405,
      headers: { allow: 'POST', 'content-type': 'text/plain; charset=utf-8' },
    });
  }

  if (request.method !== 'POST') {
    return new Response('Method not allowed', { status: 405, headers: { allow: 'POST' } });
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return Response.json(err(null, -32700, 'Parse error: body is not JSON'), { status: 400 });
  }

  // A batch is a JSON array; either shape is valid JSON-RPC.
  const batch = Array.isArray(payload) ? payload : [payload];
  const responses = batch
    .map((entry) => handleRpc(entry as JsonRpcRequest, context))
    .filter((response): response is NonNullable<typeof response> => response !== null);

  if (responses.length === 0) return new Response(null, { status: 202 });

  return Response.json(Array.isArray(payload) ? responses : responses[0], {
    headers: { 'cache-control': 'no-store' },
  });
}

/**
 * Where the shell should load the renderer from.
 *
 * An explicit `?origin=` wins, and only over http(s) — anything else is a
 * script source someone put in a URL, which is not a thing to honour.
 */
function rendererOrigin(url: URL): string {
  const override = url.searchParams.get('origin');
  if (override) {
    try {
      const parsed = new URL(override);
      if (parsed.protocol === 'https:' || parsed.protocol === 'http:') return parsed.origin;
    } catch {
      /* fall through to the request's own origin */
    }
  }
  return url.origin;
}

function handleRpc(request: JsonRpcRequest, context: RenderContext) {
  const id = request?.id ?? null;
  const params = request?.params ?? {};

  // Notifications carry no id and take no response.
  const isNotification = request?.id === undefined;

  switch (request?.method) {
    case 'initialize':
      return ok(id, {
        protocolVersion: PROTOCOL_VERSION,
        capabilities: {
          tools: { listChanged: false },
          resources: { listChanged: false, subscribe: false },
          prompts: { listChanged: false },
        },
        serverInfo: SERVER_INFO,
        instructions:
          'These tools return user interfaces, not text. Call one whenever the user is choosing ' +
          'between options, looking at an itinerary, or asking what a trip costs.\n\n' +
          'The `show_*` tools are shortcuts for the six layouts that come up most. The real ' +
          'capability is composition: call `get_a2ui_component_reference` once to learn the ' +
          'catalog — flight and hotel cards, itinerary days, maps, price summaries, stat tiles, ' +
          'sliders, date pickers, checkboxes, layout primitives — then write A2UI Express and ' +
          'send it to `render_a2ui_express` to build whatever this particular conversation needs. ' +
          'Prefer that over describing an interface in prose.\n\n' +
          'Every result carries three things: a plain-text summary you can read, an A2UI payload ' +
          `(${A2UI_MIME}) for a host with its own renderer, and an HTML view for one without. ` +
          'Interactions in the surface come back to you as the user\'s next turn, so build ' +
          'surfaces that ask a question and let the user answer by using them.\n\n' +
          'Every tool that composes content takes `surface`: `inline` answers the current ' +
          'message, `sidebar` is a persistent panel of controls, `home` is a standing summary. ' +
          'It changes what gets composed, not just where it lands.',
      });

    case 'notifications/initialized':
    case 'notifications/cancelled':
      return null;

    case 'ping':
      return ok(id, {});

    case 'tools/list':
      return ok(id, { tools: TOOLS });

    case 'tools/call':
      return callTool(id, params, context);

    case 'resources/list':
      return ok(id, { resources: RESOURCES });

    case 'resources/read':
      return readResource(id, params);

    case 'prompts/list':
      return ok(id, { prompts: PROMPTS });

    case 'prompts/get':
      if (params['name'] !== 'a2ui-express') {
        return err(id, -32602, `Unknown prompt: ${String(params['name'])}`);
      }
      return ok(id, {
        description: PROMPTS[0].description,
        messages: [{ role: 'user', content: { type: 'text', text: skillExpress } }],
      });

    default:
      if (isNotification) return null;
      return err(id, -32601, `Method not found: ${String(request?.method)}`);
  }
}

function readResource(id: unknown, params: Record<string, unknown>) {
  const uri = str(params['uri']);
  if (uri === 'a2ui://catalog/travel') {
    return ok(id, {
      contents: [{ uri, mimeType: 'application/json', text: JSON.stringify(CATALOG) }],
    });
  }
  if (uri === 'a2ui://skill/express') {
    return ok(id, { contents: [{ uri, mimeType: 'text/markdown', text: skillExpress }] });
  }
  return err(id, -32602, `Unknown resource: ${uri}`);
}

function callTool(id: unknown, params: Record<string, unknown>, context: RenderContext) {
  const name = str(params['name']);
  const args = (params['arguments'] ?? {}) as Record<string, unknown>;

  // Not a surface: this one hands back the vocabulary so the next call can
  // compose one. It is what makes the layouts generative rather than a menu.
  if (name === 'get_a2ui_component_reference') {
    return ok(id, {
      content: [{ type: 'text', text: skillExpress }],
      structuredContent: {
        catalogId: CATALOG_ID,
        version: 'v0.9.1',
        components: Object.keys(CATALOG.components ?? {}),
      },
      isError: false,
    });
  }

  let surface: Surface;
  try {
    switch (name) {
      case 'show_flight_options':
        surface = flightSurface(args);
        break;
      case 'show_hotel_options':
        surface = hotelSurface(args);
        break;
      case 'show_trip_controls':
        surface = controlsSurface(args);
        break;
      case 'show_itinerary':
        surface = itinerarySurface(args);
        break;
      case 'show_trip_dashboard':
        surface = dashboardSurface(args);
        break;
      case 'show_price_summary':
        surface = priceSurface(args);
        break;
      case 'render_a2ui_express':
        surface = {
          express: str(args['source']),
          summary: 'A custom interface.',
          surfaceId: str(args['surfaceId']) || 'mcp',
        };
        break;
      default:
        return err(id, -32602, `Unknown tool: ${name}`);
    }
  } catch (error) {
    return ok(id, toolError(error instanceof Error ? error.message : String(error)));
  }

  let messages: A2uiMessage[];
  try {
    messages = compiler.compile(surface.express, {
      surfaceId: surface.surfaceId,
      catalogId: CATALOG_ID,
      version: 'v0.9.1',
    });
  } catch (error) {
    // A compile failure is the host model's to fix, so say what broke rather
    // than returning a generic failure it cannot act on.
    return ok(
      id,
      toolError(
        `The A2UI Express did not compile: ${error instanceof Error ? error.message : String(error)}`,
      ),
    );
  }

  const content: Array<Record<string, unknown>> = [{ type: 'text', text: surface.summary }];

  if (context.view !== 'html') {
    content.push({
      type: 'resource',
      resource: {
        uri: `ui://a2ui/${surface.surfaceId}`,
        mimeType: A2UI_MIME,
        text: JSON.stringify(messages),
      },
    });
  }

  if (context.view !== 'payload') {
    // `ui://` + `text/html` is the MCP Apps / MCP-UI convention: the host
    // renders the resource in a sandboxed iframe rather than reading it. Host
    // support varies, which is why the text summary above is never optional.
    content.push({
      type: 'resource',
      resource: {
        uri: `ui://a2ui/${surface.surfaceId}.html`,
        mimeType: 'text/html',
        text: renderView(surface.surfaceId, messages, surface.summary, context.origin),
      },
    });
  }

  return ok(id, {
    content,
    structuredContent: { surfaceId: surface.surfaceId, catalogId: CATALOG_ID, messages },
    isError: false,
  });
}

function toolError(message: string) {
  return { content: [{ type: 'text', text: message }], isError: true };
}

// ---------------------------------------------------------------- surfaces
//
// Each of these composes Express and lets the compiler produce the JSON. It
// would be possible to build the A2UI messages directly, but Express is what a
// human can read in a diff — and it means these surfaces exercise exactly the
// same compiler the agent's output goes through.

function flightSurface(args: Record<string, unknown>): Surface {
  const flow = flowOf(args);
  const surfaceId = surfaceIdFor(flow, 'mcp-flights');
  const destination = str(args['destination']);

  const flexible = args['flexible'] === true;
  const trip = tripOf(args);
  const missing = missingFor(trip, 'priceFlights');
  if (missing.length > 0 && !flexible) throw new NeedsInput(missing, 'price flights');

  const { flights: all, note } = searchFlights({
    destination,
    origin: trip.origin,
    date: trip.startDate,
    cabin: trip.cabin,
    maxPrice: trip.maxFare,
    nonstopOnly: args['nonstopOnly'] === true,
  });

  const flights = all.slice(0, limitFor(flow));
  const place = resolveDestination(destination)?.city ?? destination;

  // The heading names what these fares are for. A price with no route, date or
  // party size beside it is the thing that makes an answer untrustworthy.
  const heading =
    basisOf({ ...trip, destination: place }) || `Flights to ${place} · indicative`;

  const lines = [
    `surface(${q(surfaceId)})`,
    `head = Text(${q(heading)}, variant=${q(flow === 'home' ? 'h4' : 'h3')})`,
  ];

  flights.forEach((flight, index) => {
    lines.push(
      `f${index} = FlightOption(${q(flight.airline)}, ${q(flight.departTime)}, ${q(flight.arriveTime)}, ` +
        `${q(flight.origin)}, ${q(flight.destination)}, ${q(flight.price)}, ` +
        `Event("select_flight", {id: ${q(flight.id)}, price: ${q(flight.price)}}), ` +
        `duration=${q(flight.duration)}, stops=${q(flight.stops)}, flightNumber=${q(flight.flightNumber)}, ` +
        `cabin=${q(flight.cabin)}${flight.badge ? `, badge=${q(flight.badge)}` : ''})`,
    );
  });

  lines.push(
    `foot = Text(${q(missing.length > 0 ? `${note} Indicative dates — not priced for a specific trip.` : note)}, variant="caption")`,
  );
  lines.push(`root = Column([head, ${flights.map((_f, i) => `f${i}`).join(', ')}, foot])`);

  return {
    express: lines.join('\n'),
    surfaceId,
    summary: flights.length
      ? `${flights.length} flight option(s), ${heading}, cheapest ${flights[0]!.price}.` +
        (missing.length > 0 ? ' Indicative — no date was given.' : '')
      : `No flights matched for ${heading}.`,
  };
}

function hotelSurface(args: Record<string, unknown>): Surface {
  const flow = flowOf(args);
  const surfaceId = surfaceIdFor(flow, 'mcp-hotels');
  const destination = str(args['destination']);
  const nights = int(args['nights'], 5);
  const { hotels: all, note } = searchHotels({
    destination,
    nights,
    maxNightly: typeof args['maxNightly'] === 'number' ? args['maxNightly'] : undefined,
    neighborhood: str(args['neighborhood']) || undefined,
  });

  const hotels = all.slice(0, limitFor(flow));
  const place = resolveDestination(destination)?.city ?? destination;
  const lines = [
    `surface(${q(surfaceId)})`,
    `head = Text(${q(`Stays in ${place}`)}, variant=${q(flow === 'home' ? 'h4' : 'h3')})`,
  ];

  hotels.forEach((hotel, index) => {
    lines.push(
      `h${index} = HotelCard(${q(hotel.name)}, ${q(hotel.price)}, ` +
        `Event("select_hotel", {id: ${q(hotel.id)}, name: ${q(hotel.name)}}), ` +
        `neighborhood=${q(hotel.neighborhood)}, rating=${q(hotel.rating)}, ` +
        `amenities=[${hotel.amenities.map(q).join(', ')}]` +
        `${hotel.badge ? `, badge=${q(hotel.badge)}` : ''})`,
    );
  });

  lines.push(`foot = Text(${q(note)}, variant="caption")`);
  lines.push(`root = Column([head, ${hotels.map((_h, i) => `h${i}`).join(', ')}, foot])`);

  return {
    express: lines.join('\n'),
    surfaceId,
    summary: hotels.length
      ? `${hotels.length} stay(s) in ${place} from ${hotels[0]!.price}.`
      : `No stays matched in ${place}.`,
  };
}

/**
 * The sidebar flow: controls, not content.
 *
 * Everything here is bound into the data model, so the host can read the
 * traveller's choices back out of the surface rather than parsing them out of a
 * sentence, and one commit action carries them all in its context.
 */
function controlsSurface(args: Record<string, unknown>): Surface {
  const destination = str(args['destination']);
  const place = resolveDestination(destination)?.city ?? destination;
  const travelers = int(args['travelers'], 2);
  const maxPrice = int(args['maxPrice'], 700);
  const startDate = str(args['startDate']);
  const endDate = str(args['endDate']);

  const nights =
    startDate && endDate
      ? Math.max(
          0,
          Math.round(
            (new Date(endDate).getTime() - new Date(startDate).getTime()) / 86_400_000,
          ),
        )
      : 0;

  const rfc = (date: string) => (date ? `${date}T00:00:00Z` : '');

  const lines = [
    'surface("mcp-sidebar")',
    `$/filters/start = ${q(rfc(startDate))}`,
    `$/filters/end = ${q(rfc(endDate))}`,
    `$/filters/travelers = ${travelers}`,
    `$/filters/maxPrice = ${maxPrice}`,
    `$/filters/stops = ${q(args['nonstopOnly'] === true ? 'nonstop' : 'any')}`,
    `title = Text(${q(place ? `Refine ${place}` : 'Refine the trip')}, variant="h3")`,
    'dates = DateRangePicker("Travel dates", $/filters/start, $/filters/end, ' +
      `action=Event("dates_changed")${nights > 0 ? `, nightsLabel=${q(`${nights} nights`)}` : ''})`,
    'who = TravelerCounter("Travellers", $/filters/travelers, min=1, max=8)',
    'budget = Slider("Max fare", 150, 2000, $/filters/maxPrice)',
    'stops = ChoicePicker("Stops", "mutuallyExclusive", ' +
      '[{label: "Any", value: "any"}, {label: "Nonstop only", value: "nonstop"}], $/filters/stops)',
    'apply = Button(Text("Apply"), "primary", Event("apply_filters", ' +
      '{destination: $/filters/destination, start: $/filters/start, end: $/filters/end, ' +
      'travelers: $/filters/travelers, maxPrice: $/filters/maxPrice, stops: $/filters/stops}))',
    'root = Column([title, dates, who, budget, stops, apply], align="stretch")',
  ];

  if (place) lines.splice(1, 0, `$/filters/destination = ${q(place)}`);

  return {
    express: lines.join('\n'),
    surfaceId: 'mcp-sidebar',
    summary: place
      ? `Controls for ${place}: dates, party size, fare cap and stops.`
      : 'Trip controls: dates, party size, fare cap and stops.',
  };
}

function itinerarySurface(args: Record<string, unknown>): Surface {
  const query = str(args['destination']);
  const destination = resolveDestination(query);
  if (!destination) throw new Error(`No itinerary data for '${query}'.`);

  const flow = flowOf(args);
  const surfaceId = surfaceIdFor(flow, 'mcp-itinerary');
  // The home flow is a summary, not a plan: one day, the next one.
  const days = flow === 'home' ? 1 : Math.min(Math.max(int(args['days'], 3), 1), 7);
  const start = args['startDate'] ? new Date(str(args['startDate'])) : new Date();
  const highlights = destination.highlights;

  const lines = [
    `surface(${q(surfaceId)})`,
    `head = Text(${q(destination.city)}, variant=${q(flow === 'home' ? 'h4' : 'h2')})`,
  ];
  const dayVars: string[] = [];

  // Each highlight is used once before any is reused. A three-day plan that
  // lists the same museum on days one and three reads as a bug, because it is.
  const pool = [...highlights];
  const filler = [
    { name: 'A slow morning', category: 'free', note: 'Coffee, a market, no plan' },
    { name: `Wander ${destination.city}`, category: 'outdoors', note: 'Pick a direction and walk' },
    { name: 'Dinner, late', category: 'food', note: 'Book somewhere near the hotel' },
  ];

  for (let day = 0; day < days; day++) {
    const date = new Date(start.getTime() + day * 86_400_000);
    const label = date.toUTCString().slice(0, 11);
    const activityVars: string[] = [];

    for (let slot = 0; slot < 2; slot++) {
      const highlight = pool.shift() ?? filler[(day * 2 + slot) % filler.length]!;
      const variable = `a${day}_${slot}`;
      activityVars.push(variable);
      lines.push(
        `${variable} = ActivityItem(${q(highlight.name)}, ${q(slot === 0 ? '10:00' : '16:00')}, ` +
          `category=${q(highlight.category)}, note=${q(highlight.note)})`,
      );
    }

    const dayVar = `day${day}`;
    dayVars.push(dayVar);
    lines.push(
      `${dayVar} = ItineraryDay(${q(`Day ${day + 1}`)}, [${activityVars.join(', ')}], ` +
        `date=${q(label)}, summary=${q(day === 0 ? 'Arrive and settle in' : 'A full day out')})`,
    );
  }

  lines.push(`root = Column([head, ${dayVars.join(', ')}])`);

  return {
    express: lines.join('\n'),
    surfaceId,
    summary: `A ${days}-day plan for ${destination.city}: ${destination.summary}`,
  };
}

function dashboardSurface(args: Record<string, unknown>): Surface {
  const query = str(args['destination']);
  const destination = resolveDestination(query);
  const place = destination?.city ?? query;
  const nights = int(args['nights'], 5);
  const travelers = int(args['travelers'], 2);
  const budget = int(args['budget'], 0);
  const spent = int(args['spent'], 0);

  const startDate = str(args['startDate']);
  const daysOut = startDate
    ? Math.max(0, Math.round((new Date(startDate).getTime() - Date.now()) / 86_400_000))
    : null;

  const estimate = estimateTrip({ destination: query, travelers, nights });
  const forecast = getWeather(query, startDate || undefined, 5);
  const effectiveBudget = budget || estimate.totalValue;

  const lines = [
    'surface("mcp-home")',
    `head = Text(${q(daysOut !== null ? `${daysOut} days to ${place}` : place)}, variant="h1")`,
    `t1 = StatTile("Travellers", ${q(String(travelers))}, caption=${q(`${nights} nights`)}, tone="neutral")`,
    `t2 = StatTile("Estimated", ${q(estimate.total)}, caption="all in", tone="accent")`,
    `t3 = StatTile("Spent", ${q(`$${spent.toLocaleString('en-US')}`)}, caption=${q(`of $${effectiveBudget.toLocaleString('en-US')}`)}, tone=${q(spent > effectiveBudget ? 'critical' : 'positive')})`,
    'tiles = Row([t1, t2, t3])',
    `meter = ProgressMeter("Budget used", ${spent}, ${Math.max(effectiveBudget, 1)}, ` +
      `caption=${q(`$${spent.toLocaleString('en-US')} of $${effectiveBudget.toLocaleString('en-US')}`)}, ` +
      `tone=${q(spent > effectiveBudget ? 'critical' : 'caution')})`,
    `weather = WeatherStrip([${forecast.days
      .map(
        (day) =>
          `{day: ${q(day.day)}, high: ${q(day.high)}, low: ${q(day.low)}, condition: ${q(day.condition)}}`,
      )
      .join(', ')}], place=${q(forecast.place)}, caption=${q(forecast.note)})`,
  ];

  if (destination) {
    lines.push(
      `map = MapPreview([${destination.highlights
        .slice(0, 4)
        .map((highlight) => `{label: ${q(highlight.name)}, kind: ${q(highlight.category)}}`)
        .join(', ')}], caption=${q(destination.summary)})`,
      'root = Column([head, tiles, meter, weather, map])',
    );
  } else {
    lines.push('root = Column([head, tiles, meter, weather])');
  }

  return {
    express: lines.join('\n'),
    // The dashboard *is* the home flow, so it always writes the home surface.
    surfaceId: 'mcp-home',
    summary: `${place}: ${travelers} traveller(s), ${nights} nights, estimated ${estimate.total}.`,
  };
}

function priceSurface(args: Record<string, unknown>): Surface {
  const flow = flowOf(args);
  const surfaceId = surfaceIdFor(flow, 'mcp-price');
  const query = str(args['destination']);
  const estimate = estimateTrip({
    destination: query,
    travelers: int(args['travelers'], 2),
    nights: int(args['nights'], 5),
    flightPrice: typeof args['flightPrice'] === 'number' ? args['flightPrice'] : undefined,
    nightlyPrice: typeof args['nightlyPrice'] === 'number' ? args['nightlyPrice'] : undefined,
  });

  const place = resolveDestination(query)?.city ?? query;
  const lines = estimate.lines
    .map(
      (line) =>
        `{label: ${q(line.label)}, amount: ${q(line.amount)}${line.note ? `, note: ${q(line.note)}` : ''}}`,
    )
    .join(', ');

  return {
    express: [
      `surface(${q(surfaceId)})`,
      `head = Text(${q(`What ${place} costs`)}, variant=${q(flow === 'home' ? 'h4' : 'h3')})`,
      `p = PriceSummary([${lines}], ${q(estimate.total)}, totalLabel="Trip total", ` +
        `caption="Estimated, taxes included")`,
      'root = Column([head, p])',
    ].join('\n'),
    surfaceId,
    summary: `Estimated ${estimate.total} for ${place}.`,
  };
}

export { TOOLS as MCP_TOOLS, A2UI_MIME };
