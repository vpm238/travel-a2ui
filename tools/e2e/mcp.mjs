#!/usr/bin/env node
/**
 * End-to-end check of the MCP app, against a running deployment.
 *
 * The unit tests call `handleMcp` directly, which proves the JSON-RPC contract
 * and nothing about whether the surface actually draws. That is the part that
 * breaks in someone else's app: the tool result carries a shell, the shell
 * fetches a renderer from this origin, and the frame it runs in has an opaque
 * origin and a sandbox someone else configured.
 *
 * So this speaks real JSON-RPC over HTTP, takes the HTML out of the tool result,
 * and loads it in a browser page with no origin of its own — the closest thing
 * to an MCP host's iframe that can be arranged without an MCP host. Then it
 * checks that real flight cards are on screen, that clicking one posts the event
 * a host would forward to its model, and that the shell stayed small.
 *
 *   npm run dev:worker                      # or point BASE_URL at the deploy
 *   node tools/e2e/mcp.mjs [--screenshot docs/screenshots/05-mcp-view.png]
 */

import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

const BASE = (process.env.BASE_URL ?? 'http://127.0.0.1:8787').replace(/\/$/, '');
const executablePath =
  process.env.CHROMIUM_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';

const shotIndex = process.argv.indexOf('--screenshot');
const SHOT = shotIndex === -1 ? null : process.argv[shotIndex + 1];

const failures = [];
let checks = 0;

function check(label, condition, detail = '') {
  checks += 1;
  if (condition) {
    console.log(`  ✓ ${label}`);
  } else {
    console.log(`  ✗ ${label}${detail ? ` — ${detail}` : ''}`);
    failures.push(label);
  }
}

let nextId = 1;
async function rpc(method, params) {
  const response = await fetch(`${BASE}/mcp`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: nextId++, method, params }),
  });
  if (!response.ok) throw new Error(`${method} → HTTP ${response.status}`);
  const body = await response.json();
  if (body.error) throw new Error(`${method} → ${body.error.code} ${body.error.message}`);
  return body.result;
}

async function main() {
  console.log(`MCP end-to-end against ${BASE}\n`);

  console.log('handshake');
  const init = await rpc('initialize', { protocolVersion: '2025-06-18' });
  check('the server announces itself', init.serverInfo?.name === 'travel-a2ui', init.serverInfo?.name);
  check('it tells the host these tools return interfaces', /user interfaces/i.test(init.instructions ?? ''));

  const { tools } = await rpc('tools/list');
  check('all eight tools are listed', tools.length === 8, `${tools.length} listed`);
  check(
    'every tool carries the three-flow argument or is a renderer',
    tools.every(
      (tool) =>
        tool.inputSchema.properties.surface ||
        ['show_trip_controls', 'show_trip_dashboard', 'render_a2ui_express', 'get_a2ui_component_reference'].includes(tool.name),
    ),
  );

  const { resources } = await rpc('resources/list');
  const skill = await rpc('resources/read', { uri: 'a2ui://skill/express' });
  check('the catalog and the skill are readable', resources.length === 2);
  check(
    'the skill it serves is the generated one',
    skill.contents[0].text.includes('A2UI Express') && skill.contents[0].text.length > 4000,
    `${skill.contents[0].text.length} bytes`,
  );

  console.log('\ntool call');
  const result = await rpc('tools/call', {
    name: 'show_flight_options',
    arguments: { destination: 'Madrid', travelers: 2, surface: 'inline' },
  });

  const summary = result.content.find((part) => part.type === 'text');
  const payload = result.content.find(
    (part) => part.resource?.mimeType === 'application/vnd.a2ui+json',
  );
  const view = result.content.find((part) => part.resource?.mimeType === 'text/html');

  check('a plain-text summary for a host that cannot draw', /flight option/i.test(summary?.text ?? ''));
  check('an A2UI payload for a host that can', Boolean(payload));
  check('an HTML view for everyone else', Boolean(view));

  const html = view.resource.text;
  const embedded = JSON.parse(
    html.slice(
      html.indexOf('>', html.indexOf('id="a2ui-payload"')) + 1,
      html.indexOf('</script>', html.indexOf('id="a2ui-payload"')),
    ),
  );
  const shellBytes = html.length - JSON.stringify(embedded).length;
  check('the shell is under a kilobyte', shellBytes < 1024, `${shellBytes} B`);
  check('the renderer is loaded from this deployment', html.includes(`${BASE}/mcp-view/app.js`));

  const bundle = await fetch(`${BASE}/mcp-view/app.js`);
  check('the renderer is actually served', bundle.ok, `HTTP ${bundle.status}`);
  check(
    'and readable from a frame with no origin',
    bundle.headers.get('access-control-allow-origin') === '*',
    bundle.headers.get('access-control-allow-origin') ?? 'no header',
  );

  console.log('\nrendered in a host frame');
  const browser = await chromium.launch({ executablePath });

  /**
   * The nearest thing to an MCP host we can build: a page that drops the tool
   * result into a sandboxed iframe and listens for what comes back.
   *
   * `sandbox="allow-scripts"` without `allow-same-origin` is what the hosts
   * actually use, and it is the strictest case — the frame has an opaque origin,
   * so a same-origin assumption anywhere in the renderer fails here.
   */
  async function renderInHost(page, document) {
    const errors = [];
    page.on('pageerror', (error) => errors.push(String(error)));
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text());
    });

    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    await page.evaluate((srcdoc) => {
      document.body.innerHTML = '';
      document.body.style.margin = '0';
      window.__posted = [];
      window.addEventListener('message', (event) => window.__posted.push(event.data));
      const frame = document.createElement('iframe');
      frame.id = 'surface';
      frame.setAttribute('sandbox', 'allow-scripts');
      frame.style.cssText = 'width:100%;height:100vh;border:0;display:block';
      frame.srcdoc = srcdoc;
      document.body.appendChild(frame);
    }, document);

    const frame = page.frameLocator('#surface');
    return { frame, errors, posted: () => page.evaluate(() => window.__posted) };
  }

  const page = await browser.newPage({ viewport: { width: 520, height: 800 } });
  const host = await renderInHost(page, html);

  await host.frame.locator('.tv-flight').first().waitFor({ timeout: 15_000 }).catch(() => {});
  const cards = await host.frame.locator('.tv-flight').count();
  check('real flight cards drew inside the sandbox', cards >= 3, `${cards} cards`);
  check('the renderer booted without errors', host.errors.length === 0, host.errors[0] ?? '');

  const styled = await host.frame
    .locator('.tv-flight')
    .first()
    .evaluate((card) => getComputedStyle(card).borderRadius)
    .catch(() => '');
  check('the stylesheet loaded across the origin too', styled !== '' && styled !== '0px', styled || 'unstyled');

  const heights = (await host.posted()).filter((m) => m?.type === 'ui/size-change');
  check('it told the host how tall it wants to be', heights.length > 0);

  await host.frame.locator('.tv-flight').first().click();
  await page.waitForTimeout(200);
  const actions = (await host.posted()).filter(
    (m) => m?.type === 'ui/action' || m?.type === 'a2ui.event',
  );
  const intent = actions.find((message) => message.type === 'ui/action');
  check('clicking a card posts an intent to the host', Boolean(intent), JSON.stringify(actions[0] ?? {}));
  check(
    'and it carries what the model needs to act on',
    intent?.payload?.intent === 'select_flight' && Boolean(intent.payload.params?.context?.id),
    JSON.stringify(intent?.payload ?? {}),
  );

  if (SHOT) {
    mkdirSync(dirname(SHOT), { recursive: true });
    await page.screenshot({ path: SHOT, fullPage: true });
    console.log(`\n  → ${SHOT}`);
  }

  // The generative path: read the catalog, write a layout no tool hard-codes,
  // render it with the same components. This is the capability; the `show_*`
  // tools are shortcuts.
  console.log('\ncomposed on the fly');
  const reference = await rpc('tools/call', { name: 'get_a2ui_component_reference', arguments: {} });
  const contract = reference.content[0].text;
  check('the contract carries every signature', contract.includes('FlightOption('), `${contract.length} bytes`);
  check(
    'and names components the show_* tools never touch',
    ['ExpenseSplit(', 'CheckBox(', 'Slider('].every((name) => contract.includes(name)),
  );

  const composed = await rpc('tools/call', {
    name: 'render_a2ui_express',
    arguments: {
      surfaceId: 'mcp-composed',
      source: [
        'surface("mcp-composed")',
        '$/packing/visa = false',
        'head = Text("Before you fly", variant="h3")',
        'cost = PriceSummary([{label: "Flights", amount: "$824"}, {label: "Hotel", amount: "$1,180"}], "$2,004", totalLabel="Two travellers")',
        'meter = ProgressMeter("Budget used", 2004, 2600, caption="$2,004 of $2,600", tone="caution")',
        'visa = CheckBox("Schengen visa checked", $/packing/visa)',
        'split = ExpenseSplit("Split evenly", "$2,004", [{name: "You", share: "$1,002", status: "paid"}, {name: "Sam", share: "$1,002", status: "owes"}])',
        'go = Button(Text("Looks right"), "primary", Event("confirm_budget", {total: "$2,004"}))',
        'root = Column([head, cost, meter, visa, split, go], align="stretch")',
      ].join('\n'),
    },
  });
  check('a composed layout compiles', composed.isError === false, JSON.stringify(composed.content?.[0] ?? {}));

  const composedHtml = composed.content.find(
    (part) => part.resource?.mimeType === 'text/html',
  ).resource.text;

  const composedPage = await browser.newPage({ viewport: { width: 520, height: 900 } });
  const composedHost = await renderInHost(composedPage, composedHtml);
  await composedHost.frame.locator('.tv-price').first().waitFor({ timeout: 15_000 }).catch(() => {});

  const drew = {};
  for (const [kind, selector] of [
    ['price summary', '.tv-price'],
    ['expense split', '.tv-split'],
    ['progress meter', '.tv-meter'],
    ['checkbox', 'input[type="checkbox"]'],
    ['button', 'button'],
  ]) {
    drew[kind] = await composedHost.frame.locator(selector).count();
  }
  check(
    'the composed surface drew every component kind it asked for',
    Object.values(drew).every((n) => n > 0),
    JSON.stringify(drew),
  );
  check('with no errors', composedHost.errors.length === 0, composedHost.errors[0] ?? '');

  if (SHOT) {
    const composedShot = SHOT.replace(/(\.\w+)$/, '-composed$1');
    await composedPage.screenshot({ path: composedShot, fullPage: true });
    console.log(`  → ${composedShot}`);
  }

  await browser.close();

  console.log(`\n${checks - failures.length}/${checks} checks passed`);
  if (failures.length > 0) {
    console.error(`\nFailed:\n${failures.map((name) => `  - ${name}`).join('\n')}`);
    process.exit(1);
  }
}

main().catch((error) => {
  console.error(`\n${error.message}`);
  process.exit(1);
});
