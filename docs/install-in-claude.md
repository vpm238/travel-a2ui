# Installing the travel app inside Claude

This app has two front doors and both need a model behind them:

- **the web app** — you open it in a browser, paste your own Gemini API key,
  and talk to it. The key stays in that browser; the server forwards it with
  the request and keeps nothing.
- **the MCP app** — you install it into Claude, and *Claude* becomes the model.
  There is no key to paste, because Claude is already the LLM in that
  conversation. The tools return interfaces and Claude renders them in the chat.

This page is about the second one. You need the deployment's URL first — see
[Deploy it](../README.md#deploy-it). Everywhere below, replace
`https://travel-a2ui-vy7stnte2a-uc.a.run.app` with yours.

---

## 1 · Claude Code (terminal, and the IDE extensions)

One command:

```bash
claude mcp add --transport http travel-a2ui https://travel-a2ui-vy7stnte2a-uc.a.run.app/mcp
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
      "url": "https://travel-a2ui-vy7stnte2a-uc.a.run.app/mcp"
    }
  }
}
```

`--scope user` on the `add` command does the same thing for every project you
open. There is no authentication to configure: the server holds no credentials
of its own, which is also why it holds no trip data of yours.

## 2 · claude.ai (and Claude Desktop)

A remote MCP server is added as a **custom connector**, at
[claude.ai/customize/connectors](https://claude.ai/customize/connectors):

1. **Customize → Connectors**
2. **+** → *Add custom connector*
3. Paste `https://travel-a2ui-vy7stnte2a-uc.a.run.app/mcp`
4. **Add**

Leave the OAuth fields blank. The transport is Streamable HTTP and the server is
stateless, so there is nothing else to fill in.

**Which plans.** Custom connectors work on Free, Pro, Max, Team and Enterprise —
Free is limited to one. On **Team and Enterprise only an Owner can add one**, from
*Organization settings → Connectors → Add → Custom → Web*; everyone else then
finds it under Customize → Connectors and presses **Connect**.

**Claude Desktop** signs in to the same account, so a connector added on
claude.ai is there too. Desktop's `claude_desktop_config.json` is a different
mechanism — it launches *local* MCP servers as subprocesses — and is not the way
to reach a deployment over HTTP.

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

**Eleven tools**, each pointed at the view by `_meta.ui.resourceUri`. Nine
return data; two are the vocabulary and the compiler. **Nothing here returns a
finished layout** — Claude composes those, which is the whole point of the
plugin.

| Tool | Returns |
| --- | --- |
| `search_flights` | fares, times and stops for one hop |
| `search_hotels` | nightly rates, neighbourhoods, ratings |
| `get_destination` | what is worth doing, when to go, the local currency |
| `get_weather` | a short forecast by day |
| `estimate_cost` | the trip itemised, hop by hop and stay by stay |
| `save_trip` | records what has been decided |
| `release_decision` | lets one go, and whatever depended on it |
| `get_trip` | the whole trip read back |
| `share_plan` | the trip as a page somebody outside the chat can read |
| `get_a2ui_component_reference` | the grammar and every component signature |
| `render_a2ui_express` | compiles Express Claude wrote into a live surface |

Six server-composed layouts used to be listed here too — a flight picker, stay
cards, the controls panel, an itinerary, a dashboard, a price summary. They were
removed on purpose, and that was a behavioural finding rather than a preference:
given both paths, Claude takes the one-call path every time, because it is one
call. The generative path then never runs, and a plugin whose entire argument is
that a model composes interfaces spends its life picking from a menu of six.

The three placements are still reachable — Claude names the surface it writes
into, and a surface that replaces itself behaves like a panel wherever it lands:

> Show me flights to Lisbon **as a sidebar panel**.
> Compose **a home screen** for how the Madrid trip is looking.

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
   BASE_URL=https://travel-a2ui-vy7stnte2a-uc.a.run.app node tools/e2e/mcp.mjs
   ```

## Verifying a deployment end to end

```bash
BASE_URL=https://travel-a2ui-vy7stnte2a-uc.a.run.app node tools/e2e/mcp.mjs
```

34 checks. It plays the host's side properly: reads the declared template,
answers `ui/initialize`, waits for `ui/notifications/initialized`, and only then
sends the tool result — in a real `sandbox="allow-scripts"` iframe with an
opaque origin. Then it asserts the handshake happened, the flight cards drew,
tapping one produced a `ui/message` in the conversation, and a layout composed
on the fly from the component reference drew every kind it asked for.
