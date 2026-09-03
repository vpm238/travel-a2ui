# Installing the travel app inside Claude

This app has two front doors and both need a model behind them:

- **the web app** — you open it in a browser, paste your own Anthropic API key,
  and talk to it. The key stays in that browser; the Worker forwards it and
  forgets it.
- **the MCP app** — you install it into Claude, and *Claude* becomes the model.
  There is no key to paste, because Claude is already the LLM in that
  conversation. The tools return interfaces and Claude renders them in the chat.

This page is about the second one. You need the deployment's URL first — see
[Deploy it](../README.md#deploy-it). Everywhere below, replace
`https://travel-a2ui.<subdomain>.workers.dev` with yours.

---

## 1 · Claude Code (terminal, and the IDE extensions)

One command:

```bash
claude mcp add --transport http travel-a2ui https://travel-a2ui.<subdomain>.workers.dev/mcp
```

Check it connected:

```bash
claude mcp list
```

To share it with a repository instead of your user profile, commit a `.mcp.json`
at the repo root — everyone who opens that repo is prompted to enable it:

```json
{
  "mcpServers": {
    "travel-a2ui": {
      "type": "http",
      "url": "https://travel-a2ui.<subdomain>.workers.dev/mcp"
    }
  }
}
```

`--scope user` on the `add` command does the same thing for every project you
open. There is no authentication to configure: the server holds no credentials
of its own, which is also why it holds no trip data of yours.

## 2 · Claude Desktop and claude.ai

Both take a **custom connector** pointed at the same URL.

- **Claude Desktop** — Settings → Connectors → *Add custom connector* → paste
  `https://travel-a2ui.<subdomain>.workers.dev/mcp`.
- **claude.ai** — Settings → Connectors → *Add custom connector* → same URL.
  (Custom connectors are a paid-plan feature; on a Team or Enterprise plan an
  owner may need to allow them first.)

Leave the OAuth fields blank. The transport is Streamable HTTP and the server is
stateless, so there is nothing else to fill in.

Interfaces render in the conversation and, for the panel-shaped surfaces, in
Claude's side panel — that is the host's choice, and asking for "the sidebar
version" is what nudges it (see the flows below).

## 3 · Check it works

Ask Claude, in that conversation:

> Use the travel tools to show me flights to Madrid.

You should get flight cards you can click, not a bulleted list of flights. If
you get the list, the tools are not installed or not enabled for that
conversation.

Then ask for something no tool covers:

> Read the A2UI component reference and compose me a pre-flight checklist:
> what the trip costs, how much of my $2,600 budget it uses, a visa checkbox,
> and how it splits between two people.

Claude will call `get_a2ui_component_reference`, write A2UI Express, and send it
to `render_a2ui_express`. That is the interesting one — it is composing a layout
from the catalog rather than picking from a menu.

## What Claude gets

**Eight tools**, each pointed at the view by `_meta.ui.resourceUri`.

| Tool | Returns |
| --- | --- |
| `show_flight_options` | a flight picker |
| `show_hotel_options` | stay cards with rating, neighbourhood, nightly rate |
| `show_trip_controls` | the sidebar panel: dates, party size, fare cap, stops |
| `show_itinerary` | a day-by-day plan from the destination's real highlights |
| `show_trip_dashboard` | the home screen: days out, budget, forecast, map |
| `show_price_summary` | an itemised cost breakdown |
| `get_a2ui_component_reference` | the grammar and every component signature |
| `render_a2ui_express` | compiles Express Claude wrote into a live surface |

Every tool that composes content takes `surface: inline | sidebar | home`. It
changes *what is composed*, not just where it lands — a sidebar shows three
flights and the filters that produced them, a home screen shows that a flight is
still unbooked. So the three flows from the web app are all reachable here:

> Show me flights to Lisbon **in the sidebar**.
> **On my home screen**, how is the Madrid trip looking?

**Two resources** — `a2ui://catalog/travel` (the JSON Schema catalog) and
`a2ui://skill/express` (the generated output contract). Attach either as
context; `@travel-a2ui` in Claude Code lists them.

**One prompt** — `a2ui-express`, the same contract as a slash command. In Claude
Code it appears as `/mcp__travel-a2ui__a2ui-express`. The tool version exists
because most hosts only expose prompts to the *user*, never to the model.

## What actually renders, and how

Worth understanding, because getting it wrong produces a plugin that runs the
tools and shows nothing — which is exactly what this did until it was fixed.

A host does **not** look for HTML inside a tool result. It looks for a `ui://`
resource declared in `resources/list` with the MIME type
`text/html;profile=mcp-app`, reads it once per conversation as a *template*, and
then forwards each tool result to that template over a postMessage bridge. Three
things have to line up, and all three now do:

| | What this server sends |
| --- | --- |
| the template | `ui://travel-a2ui/surface`, `text/html;profile=mcp-app`, with its CSP in `_meta.ui` |
| the link | every tool carries `_meta.ui.resourceUri` naming it |
| the surface | the A2UI messages in `structuredContent`, which is what the host forwards |

The template has the whole renderer inlined — React and the component library —
so it declares `resourceDomains: []` and fetches nothing. Nothing to fetch means
no content policy can break it. Because the template is read once rather than
per call, inlining costs nothing per tool result: the per-call payload is a few
kilobytes of A2UI.

Interactions come back as `ui/message`, a user turn in your conversation. Tapping
a flight *is* you answering, phrased in the interface rather than in prose.

**Other hosts.** `?view=payload` sends the A2UI payload alone, for a host with
its own renderer. `?view=legacy` returns the older MCP-UI shape — a `text/html`
resource per result with the payload inlined — for a host that reads those. A
host that draws neither still gets the text summary, which is the intended
floor.

## If nothing renders

In order:

1. **Check the connector is enabled *in this chat*, not just installed.** A
   connector can be connected at the org level and switched off for the
   conversation, and the symptom is identical to a broken app: no tools, no UI.
2. **Ask the host what it supports.** `resources/list` should show
   `ui://travel-a2ui/surface` with `text/html;profile=mcp-app`. If your host
   advertises a different MIME type, it is speaking a different revision.
3. **Check the tools carry `_meta.ui.resourceUri`.** Without it the host has a
   template and a tool and no reason to connect them.
4. Run the end-to-end check against your deployment, which exercises the whole
   handshake in a real sandboxed iframe:

   ```bash
   BASE_URL=https://travel-a2ui.<subdomain>.workers.dev node tools/e2e/mcp.mjs
   ```

## Verifying a deployment end to end

```bash
BASE_URL=https://travel-a2ui.<subdomain>.workers.dev node tools/e2e/mcp.mjs
```

34 checks. It plays the host's side properly: reads the declared template,
answers `ui/initialize`, waits for `ui/notifications/initialized`, and only then
sends the tool result — in a real `sandbox="allow-scripts"` iframe with an
opaque origin. Then it asserts the handshake happened, the flight cards drew,
tapping one produced a `ui/message` in the conversation, and a layout composed
on the fly from the component reference drew every kind it asked for.
