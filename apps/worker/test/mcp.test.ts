/**
 * The MCP app, tested as a protocol rather than as a set of functions.
 *
 * These go through `handleMcp` with real JSON-RPC requests, because that is the
 * contract another agent host actually depends on: the method names, the error
 * codes, the shape of a tool result. A unit test of `flightSurface` would pass
 * happily while the server returned a malformed envelope.
 */

import { describe, expect, it } from 'vitest';

import { handleMcp } from '../src/mcp.js';

const PROTOCOL_VERSION = '2025-06-18';

/**
 * The deployment's static assets, as the Worker sees them.
 *
 * The app template is composed from these rather than imported, so a test that
 * wants to read it has to supply them — which is also the check that the
 * composition works at all.
 */
const ASSETS = {
  fetch: async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path === '/mcp-view/app.js') return new Response('/* renderer */ window.__a2ui = 1;');
    if (path === '/mcp-view/app.css') return new Response('.tv-flight { border-radius: 12px }');
    return new Response('not found', { status: 404 });
  },
} as unknown as Fetcher;

async function rpc(method: string, params?: Record<string, unknown>, id: unknown = 1) {
  const response = await handleMcp(
    new Request('https://example.test/mcp', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id, method, params }),
    }),
    ASSETS,
  );
  return { status: response.status, body: (await response.json()) as any };
}

async function callTool(name: string, args: Record<string, unknown>, view?: string) {
  const response = await handleMcp(
    new Request(`https://example.test/mcp${view ? `?view=${view}` : ''}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name, arguments: args } }),
    }),
  );
  return ((await response.json()) as any).result;
}

function componentsOf(messages: any[]): any[] {
  return messages.flatMap((message) =>
    message.updateComponents ? message.updateComponents.components : [],
  );
}

describe('handshake', () => {
  it('reports the protocol version and its capabilities', async () => {
    const { body } = await rpc('initialize', { protocolVersion: PROTOCOL_VERSION });
    expect(body.result.protocolVersion).toBe(PROTOCOL_VERSION);
    expect(body.result.capabilities).toHaveProperty('tools');
    expect(body.result.capabilities).toHaveProperty('resources');
    expect(body.result.capabilities).toHaveProperty('prompts');
    expect(body.result.serverInfo.name).toBe('travel-a2ui');
  });

  it('tells the host what the tools are for', async () => {
    const { body } = await rpc('initialize');
    expect(body.result.instructions).toMatch(/user interfaces/i);
  });

  it('answers a notification with no body at all', async () => {
    const response = await handleMcp(
      new Request('https://example.test/mcp', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }),
      }),
    );
    expect(response.status).toBe(202);
  });

  it('rejects an unknown method with -32601', async () => {
    const { body } = await rpc('does/not/exist');
    expect(body.error.code).toBe(-32601);
  });

  it('rejects a malformed body with -32700', async () => {
    const response = await handleMcp(
      new Request('https://example.test/mcp', { method: 'POST', body: 'not json' }),
    );
    expect(response.status).toBe(400);
    expect(((await response.json()) as any).error.code).toBe(-32700);
  });

  it('declines GET, since this server is stateless', async () => {
    const response = await handleMcp(new Request('https://example.test/mcp'));
    expect(response.status).toBe(405);
  });

  it('answers a batch with an array', async () => {
    const response = await handleMcp(
      new Request('https://example.test/mcp', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify([
          { jsonrpc: '2.0', id: 1, method: 'ping' },
          { jsonrpc: '2.0', id: 2, method: 'tools/list' },
        ]),
      }),
    );
    const body = (await response.json()) as any[];
    expect(Array.isArray(body)).toBe(true);
    expect(body).toHaveLength(2);
  });
});

describe('tools', () => {
  it('advertises every tool with a schema', async () => {
    const { body } = await rpc('tools/list');
    const names = body.result.tools.map((tool: any) => tool.name);
    expect(names).toEqual([
      'show_flight_options',
      'show_hotel_options',
      'show_trip_controls',
      'show_itinerary',
      'show_trip_dashboard',
      'show_price_summary',
      'get_a2ui_component_reference',
      'render_a2ui_express',
    ]);
    for (const tool of body.result.tools) {
      expect(tool.description).toBeTruthy();
      expect(tool.inputSchema.type).toBe('object');
    }
  });

  it('returns a text summary and an A2UI payload', async () => {
    const result = await callTool('show_flight_options', { destination: 'Madrid', origin: 'JFK', date: '2026-04-12', travelers: 2 });
    expect(result.isError).toBe(false);

    const text = result.content.find((part: any) => part.type === 'text');
    expect(text.text).toMatch(/flight option/i);

    const payload = result.content.find(
      (part: any) => part.resource?.mimeType === 'application/vnd.a2ui+json',
    );
    expect(JSON.parse(payload.resource.text)).toEqual(result.structuredContent.messages);
  });

  /**
   * The three things that have to line up for a surface to render, and did not
   * for a long time. A host does not look for HTML in a tool result — it reads
   * the declared `ui://` template once and forwards each result to it.
   */
  describe('the contract that makes a host draw it', () => {
    it('declares the view as a resource with the MIME type a host looks for', async () => {
      const { body } = await rpc('resources/list');
      const app = body.result.resources.find((entry: any) => entry.uri === 'ui://travel-a2ui/surface');
      expect(app).toBeDefined();
      expect(app.mimeType).toBe('text/html;profile=mcp-app');
    });

    it('and tells the sandbox it needs to fetch nothing', async () => {
      const { body } = await rpc('resources/list');
      const app = body.result.resources.find((entry: any) => entry.uri === 'ui://travel-a2ui/surface');
      // Everything is inlined in the template, so no content policy can break
      // it. An empty resourceDomains is the claim, and it has to stay true.
      expect(app._meta.ui.csp.resourceDomains).toEqual([]);
      expect(app._meta.ui.csp.connectDomains).toEqual(['https://example.test']);
    });

    it('serves that template self-contained, with no payload in it', async () => {
      const { body } = await rpc('resources/read', { uri: 'ui://travel-a2ui/surface' });
      const html = body.result.contents[0];
      expect(html.mimeType).toBe('text/html;profile=mcp-app');
      expect(html.text).toContain('<!doctype html>');
      expect(html.text).not.toMatch(/<script[^>]+src=/);
      expect(html.text).not.toMatch(/<link[^>]+stylesheet/);
      // A template carries no surface: the surface arrives by notification.
      expect(html.text).not.toContain('__A2UI_PAYLOAD__');

      // Composed from the assets actually being served, so it can never be a
      // stale copy of the renderer the rest of the app is using.
      expect(html.text).toContain('window.__a2ui = 1;');
      expect(html.text).toContain('.tv-flight { border-radius: 12px }');
    });

    it('points every tool at it', async () => {
      const { body } = await rpc('tools/list');
      for (const tool of body.result.tools) {
        expect(tool._meta.ui.resourceUri).toBe('ui://travel-a2ui/surface');
      }
    });

    it('puts the surface where the host forwards it from', async () => {
      const result = await callTool('show_flight_options', {
        destination: 'Madrid',
        origin: 'JFK',
        date: '2026-04-12',
      });
      // `structuredContent` is what reaches the view as tool-result. Without
      // it the template loads and has nothing to draw.
      expect(result.structuredContent.messages.length).toBeGreaterThan(0);
      expect(result._meta.ui.resourceUri).toBe('ui://travel-a2ui/surface');
    });

    it('does not also send a competing text/html view', async () => {
      const result = await callTool('show_flight_options', {
        destination: 'Madrid',
        origin: 'JFK',
        date: '2026-04-12',
      });
      const kinds = result.content.map((part: any) => part.resource?.mimeType ?? part.type);
      expect(kinds).not.toContain('text/html');
    });

    it('speaks the version the client asked for', async () => {
      const { body } = await rpc('initialize', { protocolVersion: '2025-11-25' });
      expect(body.result.protocolVersion).toBe('2025-11-25');
      expect(body.result.capabilities.extensions['io.modelcontextprotocol/ui']).toEqual({
        mimeTypes: ['text/html;profile=mcp-app'],
      });
    });

    it('and falls back to its own when the client asks for one it does not know', async () => {
      const { body } = await rpc('initialize', { protocolVersion: '1999-01-01' });
      expect(body.result.protocolVersion).toBe('2025-11-25');
    });
  });

  it('the legacy view is a shell: surface inlined, renderer by reference', async () => {
    const result = await callTool(
      'show_flight_options',
      { destination: 'Madrid', origin: 'JFK', date: '2026-04-12' },
      'legacy',
    );
    const html = result.content.find((part: any) => part.resource?.mimeType === 'text/html')
      .resource.text as string;

    // The payload is inlined, and nothing in it can close the script block.
    const start = html.indexOf('>', html.indexOf('id="a2ui-payload"')) + 1;
    const embedded = JSON.parse(html.slice(start, html.indexOf('</script>', start)));
    expect(embedded.messages).toEqual(result.structuredContent.messages);
    expect(html).not.toContain('__A2UI_PAYLOAD__');

    // The renderer is fetched from the deployment the host just called, so a
    // preview and production each serve their own without configuration.
    expect(html).toContain('<script src="https://example.test/mcp-view/app.js" defer>');
    expect(html).toContain('href="https://example.test/mcp-view/app.css"');
    expect(html).not.toContain('__ORIGIN__');

    // A classic script, not a module: a module is fetched in CORS mode, and the
    // frame this renders in has an opaque origin.
    expect(html).not.toMatch(/<script[^>]+type="module"/);

    // Everything but the payload is a few hundred bytes. That budget is the
    // point of the shell — it rides along on every single tool result.
    const shellBytes = html.length - JSON.stringify(embedded).length;
    expect(shellBytes).toBeLessThan(1024);
  });

  it('lets a proxied deployment say where the renderer lives', async () => {
    const response = await handleMcp(
      new Request('https://internal.test/mcp?view=legacy&origin=https://travel.example.com', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          jsonrpc: '2.0',
          id: 1,
          method: 'tools/call',
          params: { name: 'show_flight_options', arguments: { destination: 'Madrid', origin: 'JFK', date: '2026-04-12' } },
        }),
      }),
    );
    const result = ((await response.json()) as any).result;
    const html = result.content.find((part: any) => part.resource?.mimeType === 'text/html')
      .resource.text as string;
    expect(html).toContain('https://travel.example.com/mcp-view/app.js');
  });

  it('ignores an origin override that is not http(s)', async () => {
    const response = await handleMcp(
      new Request('https://example.test/mcp?view=legacy&origin=javascript:alert(1)', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          jsonrpc: '2.0',
          id: 1,
          method: 'tools/call',
          params: { name: 'show_flight_options', arguments: { destination: 'Madrid', origin: 'JFK', date: '2026-04-12' } },
        }),
      }),
    );
    const result = ((await response.json()) as any).result;
    const html = result.content.find((part: any) => part.resource?.mimeType === 'text/html')
      .resource.text as string;
    expect(html).not.toContain('javascript:');
    expect(html).toContain('https://example.test/mcp-view/app.js');
  });

  it('hands the host model the whole component vocabulary', async () => {
    const result = await callTool('get_a2ui_component_reference', {});
    const text = result.content[0].text as string;

    // A host that surfaces prompts poorly still needs these signatures, which
    // is the entire reason this exists as a tool and not only as a prompt.
    expect(text).toContain('FlightOption(');
    expect(text).toContain('ExpenseSplit(');
    expect(text).toContain('Column(');
    expect(result.structuredContent.components).toContain('FlightOption');
    expect(result.isError).toBe(false);
  });

  it('compiles a layout no show_* tool hard-codes', async () => {
    const result = await callTool('render_a2ui_express', {
      surfaceId: 'mcp-composed',
      source: [
        'surface("mcp-composed")',
        '$/packing/visa = false',
        'head = Text("Before you fly", variant="h3")',
        'visa = CheckBox("Schengen visa checked", $/packing/visa)',
        'meter = ProgressMeter("Budget used", 2004, 2600, tone="caution")',
        'root = Column([head, visa, meter], align="stretch")',
      ].join('\n'),
    });

    expect(result.isError).toBe(false);
    const names = componentsOf(result.structuredContent.messages).map((c: any) => c.component);
    expect(names).toContain('CheckBox');
    expect(names).toContain('ProgressMeter');

    // Bindings survive compilation, so the checkbox is wired to the data model
    // rather than being a picture of a checkbox.
    const checkbox = componentsOf(result.structuredContent.messages).find(
      (c: any) => c.component === 'CheckBox',
    );
    expect(checkbox.value).toEqual({ path: '/packing/visa' });
  });

  it('names what was wrong when composed Express does not compile', async () => {
    const result = await callTool('render_a2ui_express', {
      source: 'root = NoSuchCard("Iberia")',
    });
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/did not compile/i);
    expect(result.content[0].text).toMatch(/NoSuchCard/);
  });

  it('lets an A2UI-native host opt out of the rendered view', async () => {
    const result = await callTool('show_flight_options', { destination: 'Madrid', origin: 'JFK', date: '2026-04-12' }, 'payload');
    const kinds = result.content.map((part: any) => part.resource?.mimeType ?? part.type);
    expect(kinds).toContain('application/vnd.a2ui+json');
    expect(kinds).not.toContain('text/html');
  });

  it('lets an MCP-UI host take the older shape instead', async () => {
    const result = await callTool(
      'show_flight_options',
      { destination: 'Madrid', origin: 'JFK', date: '2026-04-12' },
      'legacy',
    );
    const kinds = result.content.map((part: any) => part.resource?.mimeType ?? part.type);
    expect(kinds).toContain('text/html');
    expect(kinds).not.toContain('application/vnd.a2ui+json');
  });

  // An install that predates the rename should not break.
  it('still understands the old ?view=html spelling', async () => {
    const result = await callTool(
      'show_flight_options',
      { destination: 'Madrid', origin: 'JFK', date: '2026-04-12' },
      'html',
    );
    expect(result.content.map((p: any) => p.resource?.mimeType ?? p.type)).toContain('text/html');
  });

  it('renders flights as FlightOption components with actions', async () => {
    const result = await callTool('show_flight_options', { destination: 'Madrid', origin: 'JFK', date: '2026-04-12' });
    const flights = componentsOf(result.structuredContent.messages).filter(
      (component) => component.component === 'FlightOption',
    );
    expect(flights.length).toBeGreaterThan(0);
    for (const flight of flights) {
      expect(flight.action.event.name).toBe('select_flight');
      expect(flight.price).toMatch(/^\$/);
      expect(flight.origin).toHaveLength(3);
    }
  });

  it('says how many options it is actually showing', async () => {
    const result = await callTool('show_flight_options', { destination: 'Madrid', origin: 'JFK', date: '2026-04-12' });
    const shown = componentsOf(result.structuredContent.messages).filter(
      (component) => component.component === 'FlightOption',
    ).length;
    expect(result.content[0].text).toContain(`${shown} flight option`);
  });

  it('renders stays as HotelCard components', async () => {
    const result = await callTool('show_hotel_options', { destination: 'Lisbon', nights: 4 });
    const hotels = componentsOf(result.structuredContent.messages).filter(
      (component) => component.component === 'HotelCard',
    );
    expect(hotels.length).toBeGreaterThan(0);
    expect(hotels[0].amenities.length).toBeGreaterThan(0);
  });

  it('never repeats an activity while unused ones remain', async () => {
    const result = await callTool('show_itinerary', { destination: 'Lisbon', days: 3 });
    const titles = componentsOf(result.structuredContent.messages)
      .filter((component) => component.component === 'ActivityItem')
      .map((component) => component.title);
    expect(new Set(titles).size).toBe(titles.length);
  });

  it('builds a dashboard out of tiles, a meter and a forecast', async () => {
    const result = await callTool('show_trip_dashboard', {
      destination: 'Madrid',
      nights: 6,
      travelers: 2,
      budget: 2600,
      spent: 1320,
    });
    const kinds = componentsOf(result.structuredContent.messages).map((c) => c.component);
    expect(kinds).toContain('StatTile');
    expect(kinds).toContain('ProgressMeter');
    expect(kinds).toContain('WeatherStrip');
    expect(kinds).toContain('MapPreview');
  });

  it('marks an over-budget trip as critical', async () => {
    const result = await callTool('show_trip_dashboard', {
      destination: 'Madrid',
      budget: 1000,
      spent: 2400,
    });
    const meter = componentsOf(result.structuredContent.messages).find(
      (component) => component.component === 'ProgressMeter',
    );
    expect(meter.tone).toBe('critical');
  });

  it('compiles Express the host wrote itself', async () => {
    const result = await callTool('render_a2ui_express', {
      surfaceId: 'custom',
      source: 'h = Text("Hello", variant="h2")\nroot = Column([h])',
    });
    expect(result.isError).toBe(false);
    expect(result.structuredContent.surfaceId).toBe('custom');
    expect(componentsOf(result.structuredContent.messages).map((c) => c.id)).toContain('root');
  });

  it('explains a compile failure instead of just failing', async () => {
    const result = await callTool('render_a2ui_express', {
      source: 'root = Text("hi", colour="red")',
    });
    expect(result.isError).toBe(true);
    // The host's model has to be able to fix this from the message alone.
    expect(result.content[0].text).toContain('colour');
    expect(result.content[0].text).toContain('text, variant');
  });

  it('reports an unknown destination as an error the host can act on', async () => {
    const result = await callTool('show_itinerary', { destination: 'Atlantis' });
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/Atlantis/);
  });

  it('writes each flow to its own surface, and the panels are singular', async () => {
    const inline = await callTool('show_flight_options', { destination: 'Madrid', origin: 'JFK', date: '2026-04-12' });
    const sidebar = await callTool('show_flight_options', { destination: 'Madrid', origin: 'JFK', date: '2026-04-12', surface: 'sidebar' });
    const home = await callTool('show_flight_options', { destination: 'Madrid', origin: 'JFK', date: '2026-04-12', surface: 'home' });

    expect(inline.structuredContent.surfaceId).toBe('mcp-flights');
    expect(sidebar.structuredContent.surfaceId).toBe('mcp-sidebar');
    expect(home.structuredContent.surfaceId).toBe('mcp-home');
  });

  it('shows fewer options where there is less room', async () => {
    const count = async (surface?: string) => {
      const result = await callTool('show_flight_options', {
        destination: 'Madrid',
        origin: 'JFK',
        date: '2026-04-12',
        ...(surface ? { surface } : {}),
      });
      return componentsOf(result.structuredContent.messages).filter(
        (component) => component.component === 'FlightOption',
      ).length;
    };
    expect(await count('home')).toBeLessThanOrEqual(await count('sidebar'));
    expect(await count('sidebar')).toBeLessThanOrEqual(await count());
  });

  it('the sidebar flow returns controls, bound and committable', async () => {
    const result = await callTool('show_trip_controls', {
      destination: 'Madrid',
      startDate: '2026-04-12',
      endDate: '2026-04-18',
      travelers: 2,
      maxPrice: 600,
    });

    const components = componentsOf(result.structuredContent.messages);
    const kinds = components.map((component) => component.component);
    expect(kinds).toContain('DateRangePicker');
    expect(kinds).toContain('TravelerCounter');
    expect(kinds).toContain('Slider');
    expect(kinds).toContain('ChoicePicker');

    // Every control writes back to the data model, and one action carries it.
    const counter = components.find((c) => c.component === 'TravelerCounter');
    expect(counter.value).toEqual({ path: '/filters/travelers' });

    const apply = components.find((c) => c.component === 'Button');
    expect(apply.action.event.name).toBe('apply_filters');
    expect(apply.action.event.context.travelers).toEqual({ path: '/filters/travelers' });

    const data = result.structuredContent.messages.find((message: any) => message.updateDataModel);
    expect(data.updateDataModel.value.filters.travelers).toBe(2);
    expect(data.updateDataModel.value.filters.maxPrice).toBe(600);
    expect(result.structuredContent.surfaceId).toBe('mcp-sidebar');
  });

  it('the sidebar works before a destination is chosen', async () => {
    const result = await callTool('show_trip_controls', {});
    expect(result.isError).toBe(false);
    expect(result.content[0].text).toMatch(/controls/i);
  });

  it('rejects an unknown tool name', async () => {
    const { body } = await rpc('tools/call', { name: 'nope', arguments: {} });
    expect(body.error.code).toBe(-32602);
  });

  it('names the three flows on the tools that place a surface', async () => {
    const { body } = await rpc('tools/list');
    const placed = body.result.tools.filter((tool: any) => tool.inputSchema.properties?.surface);
    expect(placed.length).toBeGreaterThanOrEqual(4);
    for (const tool of placed) {
      expect(tool.inputSchema.properties.surface.enum).toEqual(['inline', 'sidebar', 'home']);
    }
  });

  it('is deterministic: the same arguments give the same surface', async () => {
    const first = await callTool('show_flight_options', { destination: 'Madrid', origin: 'JFK', date: '2026-04-12' });
    const second = await callTool('show_flight_options', { destination: 'Madrid', origin: 'JFK', date: '2026-04-12' });
    expect(first.structuredContent).toEqual(second.structuredContent);
  });
});

describe('inputs a host must supply', () => {
  it('refuses to price flights against a date nobody gave', async () => {
    const result = await callTool('show_flight_options', { destination: 'Madrid', origin: 'JFK' });
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/when you are leaving/);
    // The error is addressed to the host's model, so it names the way out.
    expect(result.content[0].text).toMatch(/\$\/trip\/startDate/);
    expect(result.content[0].text).toMatch(/flexible/);
  });

  it('refuses to price flights from an airport nobody gave', async () => {
    const result = await callTool('show_flight_options', {
      destination: 'Madrid',
      date: '2026-04-12',
    });
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/which airport you are flying from/);
  });

  it('answers a deliberately rough question, marked as rough', async () => {
    const result = await callTool('show_flight_options', {
      destination: 'Madrid',
      flexible: true,
    });
    expect(result.isError).toBe(false);
    expect(result.content[0].text).toMatch(/[Ii]ndicative/);
  });

  it('puts the route, date and party size in the heading it draws', async () => {
    const result = await callTool('show_flight_options', {
      destination: 'Madrid',
      origin: 'JFK',
      date: '2026-04-12',
      travelers: 2,
    });
    const heading = componentsOf(result.structuredContent.messages).find(
      (component) => component.id === 'head',
    );
    expect(heading.text).toContain('JFK → Madrid');
    expect(heading.text).toContain('12 Apr');
    expect(heading.text).toContain('2 travellers');
  });
});

describe('resources and prompts', () => {
  it('serves the catalog and the skill', async () => {
    const { body } = await rpc('resources/list');
    const uris = body.result.resources.map((resource: any) => resource.uri);
    expect(uris).toContain('a2ui://catalog/travel');
    expect(uris).toContain('a2ui://skill/express');
  });

  it('returns the catalog as parseable JSON with the travel components', async () => {
    const { body } = await rpc('resources/read', { uri: 'a2ui://catalog/travel' });
    const catalog = JSON.parse(body.result.contents[0].text);
    expect(catalog.components).toHaveProperty('FlightOption');
    expect(catalog.components).toHaveProperty('Text');
  });

  it('serves the Express skill as the prompt that teaches render_a2ui_express', async () => {
    const { body } = await rpc('prompts/get', { name: 'a2ui-express' });
    const text = body.result.messages[0].content.text;
    expect(text).toContain('A2UI Express output contract');
    expect(text).toContain('FlightOption(');
  });

  it('rejects an unknown resource', async () => {
    const { body } = await rpc('resources/read', { uri: 'a2ui://nope' });
    expect(body.error.code).toBe(-32602);
  });
});
