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

**Eight tools.**

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

## What actually renders, and when it doesn't

A tool result carries a summary, an A2UI payload, and a `text/html` shell of
about 450 bytes: the surface inlined, plus a `<script src>` back to your
deployment for the renderer. If a host draws the HTML, you get real components.
If it doesn't, the summary still answers the question.

Two consequences worth knowing:

- **The frame fetches from your Worker.** The renderer is served from
  `/mcp-view/app.js` with `access-control-allow-origin: *`, because the frame
  it loads into has an opaque origin. If your deployment is behind something
  that blocks that, surfaces will not draw. `?origin=https://…` on the MCP URL
  points the shell somewhere else if your public origin differs from the one
  the host calls.
- **MCP Apps support varies by host and is still moving.** A host that hasn't
  shipped HTML resources shows the summary text instead. That is the intended
  floor, not a failure — and a host with its own A2UI renderer can take the
  payload directly with `?view=payload` on the URL you installed.

## Verifying a deployment end to end

```bash
BASE_URL=https://travel-a2ui.<subdomain>.workers.dev node tools/e2e/mcp.mjs
```

24 checks: the handshake, the tool list, the three parts of a tool result, the
shell's size, that the renderer is served and CORS-readable, that flight cards
draw inside a `sandbox="allow-scripts"` iframe, that clicking one posts the
intent a host forwards to its model, and that a composed layout compiles and
draws every component it asked for.
