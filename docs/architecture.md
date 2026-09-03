# Architecture

The claim this repository is built to test:

> A generative interface is a *protocol*, not a feature of one app. Write the
> component catalog, the compiler and the renderer once, and the same surfaces
> should draw in your own app, in someone else's chat client, and under whichever
> agent runtime you feel like running today.

Everything below is how that is arranged, and — as importantly — where it isn't
true and why.

---

## 1 · One build, four places

There are exactly four things that are written once, and everything else is a
thin adapter around them.

```
                    ┌───────────────────────────────────────┐
                    │  catalogs/a2ui-travel/catalog.json     │  the vocabulary
                    │  40 components, JSON Schema            │
                    └────────────────┬──────────────────────┘
                                     │  generated from
                    ┌────────────────┴──────────────────────┐
                    │  scripts/build_catalog.py             │  ← edit here
                    └────────────────┬──────────────────────┘
                                     │
             ┌───────────────────────┼───────────────────────┐
             │                       │                       │
   ┌─────────▼─────────┐  ┌──────────▼─────────┐  ┌──────────▼─────────┐
   │ packages/express  │  │ packages/renderer  │  │ skills/*/SKILL.md  │
   │ Express ⇄ A2UI    │  │ React components   │  │ what the model     │
   │ compiler +        │  │ for every catalog  │  │ is told, generated │
   │ decompiler +      │  │ entry              │  │ from the catalog   │
   │ stream splitter   │  │                    │  │                    │
   └─────────┬─────────┘  └──────────┬─────────┘  └──────────┬─────────┘
             │                       │                       │
   ══════════╪═══════════════════════╪═══════════════════════╪══════════
             │        consumed, never reimplemented, by       │
   ┌─────────▼────────┬──────────────▼──────────┬─────────────▼────────┐
   │ apps/web         │ apps/mcp-view           │ apps/worker          │
   │ the React app    │ the same renderer, for  │ agent loop + the MCP │
   │ (3 flows)        │ an MCP host's iframe    │ server + compile API │
   └──────────────────┴─────────────────────────┴──────────────────────┘
   ┌──────────────────┬─────────────────────────────────────────────────┐
   │ apps/gallery     │ backends/claude-managed-agent (Python)          │
   │ static showcase  │ same wire protocol, Anthropic runs the loop     │
   └──────────────────┴─────────────────────────────────────────────────┘
```

There is a fifth, `packages/trip`, which the catalog does not generate: what a
trip *is*, shared by the agent, the tools, the prompt and the browser. See
[The trip is a model](#the-trip-is-a-model-not-a-bag-of-keys).

**The catalog is the single source of truth.** `scripts/build_catalog.py` is the
only file you edit to add a component; `npm run generate` then regenerates the
catalog JSON, the compiled examples, and all four `SKILL.md` files. `npm run
check` fails CI if any of them drifts, so "the docs are stale" is not a state
this repo can be in.

A component is only *complete* when three things exist: a schema entry in
`build_catalog.py`, a React case in `packages/renderer/src/components/`, and an
example in `catalogs/a2ui-travel/examples/`. The Catalog tab in the running app
flags any component with a schema but no renderer, in red, so the gap is visible
rather than discovered at runtime.

### What is *not* shared, and why

| Thing | Per-surface, because |
| --- | --- |
| Layout chrome | a chat feed, a 340 px panel and an iframe are different shapes |
| The runtime picker | only the web app chooses its backend; inside Claude, Claude *is* the runtime |
| Session storage | the Worker uses a Durable Object; the managed agent's session holds its own history |
| Conversation lifetime | a reload starts a new one in the web app; in Claude, the host owns the thread |
| Tool execution | the Worker calls its own functions; the managed agent calls the MCP server |

---

## 2 · Where this sits in the A2UI × MCP Apps design space

Google's [A2UI and MCP Apps](https://developers.googleblog.com/a2ui-and-mcp-apps/)
post enumerates three ways to combine the two. This project deliberately ships
**patterns 1 and 3 in the same tool result**, and deliberately does not ship
pattern 2.

| | Pattern | Here? |
| --- | --- | --- |
| 1 | **A2UI over MCP** — the tool returns an A2UI payload and the *host* renders it with its own design system, no iframe | ✅ the `application/vnd.a2ui+json` resource |
| 2 | **MCP Apps inside A2UI components** — a native surface embeds someone else's iframe for one state-heavy module | ❌ nothing here needs it |
| 3 | **A2UI inside an MCP App** — the app bundle carries its own A2UI renderer and draws payloads inside its sandbox | ✅ the `text/html` shell |

A single `tools/call` result carries a text summary, the pattern-1 payload, and
the pattern-3 shell. A host takes whichever it understands and ignores the rest;
a host that understands neither still gets a usable sentence. `?view=payload`
and `?view=html` drop one or the other for a host that knows what it wants.

Pattern 3 is the one that does the work today, because almost no host renders
A2UI natively yet. Pattern 1 is the one worth having, because the moment a host
does, the same server gets better without redeploying: the payload was always
there.

### The pattern-3 shell, in detail

The obvious implementation of pattern 3 is to inline the whole renderer into
every tool result. That is 230 kB of HTML per call, on every call, spent against
the host's result budget — and the renderer is byte-identical each time.

So the HTML resource is a **shell** of about 450 bytes:

```html
<link rel="stylesheet" href="__ORIGIN__/mcp-view/app.css">
<script id="a2ui-payload" type="application/json">__A2UI_PAYLOAD__</script>
<div id="root"></div>
<script src="__ORIGIN__/mcp-view/app.js" defer></script>
```

- `__A2UI_PAYLOAD__` is substituted per call. It is the only part that varies,
  it is small, and inlining it means no second round trip before the first
  paint. `</script` is escaped inside it; that is the whole of the injection
  story, and it is why the payload lives in a JSON script block rather than in
  a JS string literal.
- `__ORIGIN__` is substituted from the URL the host just called, so production,
  a preview and `wrangler dev` each serve their own renderer with nothing
  configured. `?origin=` overrides it for a tunnel or a proxy, and non-http(s)
  values are rejected.
- The bundle is a **classic script, not a module**. The frame has an opaque
  origin, and a module script is fetched in CORS mode; a classic one is not.
  `/mcp-view/*` is still served with `access-control-allow-origin: *` for the
  stylesheet and for any host that adds `crossorigin`.

`tools/e2e/mcp.mjs` renders a real tool result inside a real
`sandbox="allow-scripts"` iframe and asserts the cards draw, so this is checked
rather than assumed.

---

## 3 · The three flows

They are properties of *where an answer goes*, not of this codebase, which is
why the same three exist in the web app and in the MCP server.

| Flow | Surface id | Lifetime | What it composes |
| --- | --- | --- | --- |
| **inline** | `inline-{n}` per turn | appended, never replaced | one job — a picker, a summary, an action that continues the conversation |
| **sidebar** | `sidebar` (singular) | replaced on every write | controls for the trip as a whole: dates, party size, budget, stops |
| **home** | `home` (singular) | replaced on every write | where the trip stands today, read first, not in reply to anything |

Singular ids are what make a panel a panel rather than a feed: writing to
`sidebar` again replaces it. The MCP tools take `surface` as an argument and
`limitFor()` narrows the content accordingly — four flights inline, three in a
sidebar, two on a home screen — because the same six flights that read well
inline read as a wall in a 340 px column.

A fourth modality, the MCP app, carries all three rather than being a fourth
kind of layout.

---

## 4 · The interaction model

Three rules, and every one of them was learned by getting it wrong first.

### Editing is not deciding

| | Components | What a change does |
| --- | --- | --- |
| **Editors** | Slider, CheckBox, ChoicePicker, TextField, DateTimeInput, DateRangePicker, TravelerCounter | writes the data model, sends nothing |
| **Decisions** | Button, and tappable cards — FlightOption, HotelCard, ActivityItem | sends the whole surface back as a turn |

The first version fired a turn on every interaction. Choosing a departure
airport, a date and a party size was three turns, each answered with a *new*
surface that had forgotten the previous two — so the third question arrived
under a card that had lost the first two answers. It felt like arguing with
something that had no memory, because it was.

So: **one thing to choose → tappable cards, no button**; picking the flight is
the answer. **More than one → editors and a commit button**; the traveler sets
them all and presses once. It is enforced in three places, because a rule this
load-bearing should not depend on the model complying: editors do not call
`runAction`, the host drops editor events if one ever does, and the prompt
tells the model which is which.

When the model forgets a commit button, the host draws its own — a bar naming
how many values are unsent and a Send. A card of sliders you cannot submit is
worse than no card.

### An answered surface goes grey

Only the newest surface accepts input. Everything above it answered a message
the conversation has moved past; clicking it would answer a settled question
against a data model describing a trip that no longer exists. Spent surfaces
stay on screen as the record of what was chosen and get `inert` plus a
greyscale filter — the greying matters, because a control that looks live and
does nothing is worse than one that looks finished.

### The trip is a model, not a bag of keys

`packages/trip` is the schema, and it is the only definition. Before it existed
the agent, the tools, the prompt and the browser each had their own opinion
about what a trip was, and every bug worth reporting came out of that gap: dates
in two formats, `cabin` arriving from a picker as `["economy"]` and reaching a
tool expecting `"economy"`, "is this priceable yet" answered three different
ways, two copies of the field list drifting apart.

It carries four things:

- **`FIELDS`** — what a trip is made of. Seventeen fields across seven stages,
  each with the kind it holds and how to name it when asking a person for it.
- **`normalize`** — the only way values get in. It coerces the shapes a real
  interface produces: a picker's single-item array, an RFC 3339 instant from a
  date input, `"$2,600"` typed into a text field.
- **`missingFor` / `canDo`** — "can this be priced yet", answered once for
  everyone. The tool gate, the prompt and the UI all call it.
- **`plan`** — the trip as a sequence of steps, which is what makes the agent
  lead instead of wait.

It has no dependencies and no I/O, because it is imported by a Cloudflare
Worker, a browser bundle and a test suite alike.

### The agent leads, and finishes

A planner that answers questions is a search box with better manners. So the
model knows the order things get decided — route, dates, party, flight, stay,
budget, days — and `nextStepFor(trip)` goes into every prompt as an instruction:
here is where the trip stands, here is the next thing, end the turn having moved
it on or having asked exactly what it takes to. When every stage is settled it
says so, and the agent stops inventing questions and wishes them a good trip.

The sidebar shows the same sequence as a checklist, read from the same model, so
the panel cannot disagree with what the agent thinks is left.

**Real trips bend the plan**, and the model bends with them:

- **`skip`** — stages this trip does not need. Driving rather than flying,
  staying with family, no fixed budget. A skipped stage counts as settled and is
  never asked about again, which is the difference between a planner and a form.
- **`legs`** — the route after the first stop. Each leg carries its own dates,
  its own origin when it is not simply the previous stop, its own party size
  when that differs, and a purpose when it has one.

The party size is the part worth dwelling on, because it is where a simpler
model quietly gets the answer wrong:

> SFO to New York with two nights in Chicago for a wedding, then home — two
> tickets back, because a friend is coming with me.

That is one trip, three legs, two party sizes and a return that is not a mirror
of the outbound. With a single `travelers` the way home is priced for one person
and the friend has no seat, silently. `stops()` resolves each leg against the
trip and the leg before it — an omitted origin means "from wherever I just was",
an omitted party size means "same as the rest" — so nothing downstream
reimplements those defaults, and `partyVaries()` tells the interface when the
difference is worth showing. The agent records the whole route in one
`save_trip` and then asks only for the dates.

### `/trip` is shared; everything else is per-surface

This is the fix for "it forgot what I told you", and it is structural rather
than a prompt instruction.

```
  the trip (durable, server-side)
        │  seeded into every new surface, and synced live into the panels
        ▼
  surface data model  →  /trip/startDate, /trip/origin, /trip/travelers, …
        │  merged back on commit, before the model sees the turn
        ▼
  the trip
```

A surface is born with `/trip` already filled in from what is decided, so a
`DateRangePicker` bound to `$/trip/startDate` shows the agreed date without the
model doing anything. Committing sends those values back, and the Worker merges
them into the trip *before* building the prompt — so what the traveler set on
screen is recorded because the host recorded it, not because the model
remembered to call `save_trip`.

The sidebar and home surfaces are synced on every trip change, with no model in
the path: change the route on an inline card and the panel updates immediately.
The model is only asked to rebuild a panel when it should be a *different
shape* — a destination appearing, a flight being chosen — not when a value
moves.

---

## 5 · What the agent may not assume

An agent that invents an input produces a real-looking answer to a question
nobody asked. The two that came up:

- **Dates.** It priced "a sample 12 April departure" and showed the fares as if
  they were the traveler's.
- **Where they are.** Every trip departed from JFK, because that was the
  default.

Prompt rules were not enough — a model in a hurry prices the plausible week and
calls it a sample. So the tools enforce it: `search_flights`, `search_hotels`
and `estimate_cost` return `{ needs: 'dates' }` and an instruction to draw a
picker rather than returning numbers. `flexible: true` is the deliberate way
through for "roughly what does Madrid cost in April", and what comes back is
labelled indicative. `save_trip` refuses a range that ends before it starts.

For location the browser sends its timezone, which the Worker maps to a
departure airport and offers to the model as an explicit *suggestion* — London
for `Europe/London`, Delhi for `Asia/Kolkata`, a regional hub when the zone is
not listed, and nothing at all when it cannot tell. The model must offer it
pre-filled and let the traveler change it.

The per-turn prompt names the fields still missing rather than dumping the trip
as JSON, because a model asked to infer what is absent tends to fill the gap in
itself.

Every surface showing a price states what it is priced against — route, dates,
party size — in its heading. `LHR → Madrid · 12–19 Apr · 3 travellers`, not
`Flights to Madrid`.

---

## 6 · A turn, end to end

```
 browser                    Worker                       Anthropic
 ───────                    ──────                       ─────────
 POST /api/chat  ─────────▶ runTurn()
 x-anthropic-key            │  build system prompt from
                            │  skills/<variant>/…/SKILL.md
                            │  (cached at a prompt breakpoint)
                            ├──── messages.stream ─────────▶
                            │
                            │◀─── text deltas ─────────────┤
                            │
                            │  ExpressStreamParser.push()
                            │  splits prose from <a2ui> blocks
                            │  and recompiles the open block
                            │
      ◀── SSE: text ────────┤   prose
      ◀── SSE: ui ──────────┤   partial surface, then done:true
                            │
                            │◀─── tool_use ────────────────┤
                            │  execute, all in parallel
                            ├──── tool results ───────────▶
                            │
      ◀── SSE: done ────────┤
 store.apply(messages)
 <A2uiSurface/> renders
 user clicks a card
      ──── next turn ──────▶  "[interface] select_flight (id: "IB6250", …)"
```

Two decisions in there are load-bearing:

**Prose and UI are split server-side, as the model streams.** The model emits
one text stream containing both; `ExpressStreamParser` separates them and
recompiles the partial Express block on every chunk, so a surface materialises
progressively instead of appearing all at once at the end. Doing this in the
browser instead would mean shipping raw Express to the client and rendering it
as prose for a few hundred milliseconds — which is exactly the bug the first
version of the e2e test caught.

**A turn is a sequence of parts, not "prose then UI".** A model says a sentence,
draws, and says another. Rendering all the prose above all the surfaces puts
"want me to hold one?" above the thing being held, so `TurnPart[]` interleaves
them in arrival order. Each tool round starts a new text part, because two
sentences separated by a tool call are two paragraphs — concatenated they read
as `…anything.Nothing nonstop is showing`, which looks like a typo.

**A reload is a new conversation.** The session id is generated per page load
and deliberately not persisted, so reloading clears the transcript and the trip
— which is what a person means by reloading a demo. The API key does persist;
losing that would be a more annoying kind of forgetting. Every write to a
session pushes a 24-hour alarm out, and the alarm deletes it, so the abandoned
Durable Object each reload leaves behind expires instead of accumulating.

**Clicking is a turn.** An interface event becomes
`[interface] select_flight (id: "IB6250", price: "$412")` plus the surface's
data model. Filling in a form *is* what the user said, so it goes in as the
user's message rather than as an out-of-band state update.

---

## 7 · Two runtimes, one wire protocol

The header's **Runtime** picker switches between them mid-conversation.

| | Cloudflare Worker | Claude Managed Agent |
| --- | --- | --- |
| Who runs the loop | this Worker, at the edge | Anthropic |
| Language | TypeScript | Python |
| Prompt | assembled per request | uploaded once, versioned; sessions pin a version |
| History | Durable Object (SQLite) | the managed session |
| Tools | functions in the Worker | the MCP server, called by Anthropic |
| Compiler | `packages/express` in-process | `/api/compile` on the Worker |
| Needs | one deploy | a second service, and a **public** MCP URL |

### The agent is not the memory

Worth stating plainly, because "the conversation was forgotten" sounds like
something needs re-provisioning and it never does:

| | What it is | Lifetime |
| --- | --- | --- |
| **the agent** | a stored, versioned *configuration* — model, system prompt, tools, MCP servers. Holds no memory. | created once by `setup_agent`, shared by every conversation |
| **the session** | the memory: the transcript and the trip | one per conversation, created on first message |

A reload starts a new session against the same agent. Nothing is provisioned, no
setup cost is paid, and nothing is remembered. Re-run
`setup_agent --update` only when the *configuration* changes — a different
model, another skill variant, a moved MCP URL — which bumps the agent's version;
sessions already running stay pinned to the version they started on. If the
agent or environment has genuinely been deleted upstream, session creation says
so and names the command to run.

The Worker works the same way with different nouns: the system prompt is
assembled per request from the generated skill, and the Durable Object is the
memory.

They are interchangeable because they emit the same SSE event stream against the
same `/api/chat` contract. `probeBackend()` calls the target's `/api/meta`
before switching, so choosing a runtime that is not running says so in the
picker rather than failing on the next message.

The managed-agent backend does not ship its own compiler. The published
`a2ui-agent-sdk` (0.5.0) rejects keyword arguments in Express and emits v1.0
messages, so it cannot compile the grammar the skills teach; rather than
maintaining a third compiler, `ServiceCompiler` POSTs to the Worker's
`/api/compile`. `sdk_supports_current_grammar()` probes at startup and uses the
SDK directly if a future version can handle it.

**One compiler, two implementations, pinned to each other.** The TypeScript port
in `packages/express` is byte-checked against Google's reference Python compiler
on 20 golden cases (`packages/express/test/parity.test.ts`), and the Python
skill generator is byte-checked against the reference generator
(`tools/skillgen/tests/test_sdk_parity.py`). A `reference-parity` CI job
installs the real `a2ui-agent-sdk` and diffs. Divergence is a test failure, not
a discovery.

---

## 8 · The MCP server

Stateless Streamable HTTP: every POST is self-contained, which is all a Worker
wants to be and means no session affinity to arrange.

Eight tools, in two groups:

- **Six `show_*` tools** take structured arguments and return a surface composed
  server-side from the catalog. The host's model decides *what* to show; this
  server decides how. Fast, deterministic, no second model in the path.
- **`get_a2ui_component_reference` → `render_a2ui_express`** is the general
  case, and the `show_*` tools are shortcuts for it. The first returns the
  generated output contract — grammar, streaming rules, every positional
  signature. The model reads it once, writes Express for the layout this
  conversation actually needs, and the second compiles it.

The reference is exposed as a **tool** and not only as an MCP prompt because
hosts surface prompts to the *user*, as something to invoke by hand. A model
that can only read prompts can never learn the vocabulary mid-conversation. As a
tool it can, and that is the difference between generative layouts and a menu of
six cards.

A compile failure is returned as an `isError` result naming what was wrong —
including an invented component name, with the list of real ones — because the
host's model is the one who can fix it and a generic failure gives it nothing to
act on.

---

## 9 · Where the API key lives

Nowhere on the server. The browser holds it, sends it in `x-anthropic-key` on
each request, and the Worker passes it to the SDK and forgets it. It is never
written to a Durable Object, never logged, and never put in a URL — a key in a
query string lands in every access log between the browser and the edge.

`#key=…` in the fragment is the supported way to hand one over, because a
fragment is never sent to a server. `?key=…` also works and the app takes it,
strips it from the address bar, and then tells you plainly that the server saw
it and to rotate it.

For a shared deployment that does not want to ask, an `ANTHROPIC_API_KEY` Worker
secret is used when the header is absent.

Inside Claude, none of this applies: Claude is already the model, so the MCP
server holds no credentials at all — which is also why it holds no trip data.

---

## 10 · Testing, and what is simulated

| Layer | How |
| --- | --- |
| Trip model | 28 cases: coercion from real interface shapes, readiness, the plan, skipped stages, and a three-leg route with two party sizes |
| Compiler | 20 golden cases byte-checked against the reference Python compiler |
| Skill generator | output byte-identical to the reference generator |
| Renderer store | bindings, checks, templates, surface lifecycle |
| MCP server | real JSON-RPC through `handleMcp`, not unit calls into helpers |
| Agent loop | scripted model output through the real stream splitter |
| Web app | `tools/e2e/chat.mjs` — a real browser, a real turn, 14 assertions |
| Interaction model | `tools/e2e/interaction.mjs` — editing sends nothing, committing sends everything, spent surfaces go inert, 17 assertions |
| MCP app | `tools/e2e/mcp.mjs` — a live server, a sandboxed iframe, 24 assertions |
| Freshness | `npm run check` fails if catalog, examples or skills drift |

184 unit tests, 44 Python tests, 58 browser assertions across three end-to-end runs.

**Simulated:** flight and hotel inventory, weather, and destination highlights
(`apps/worker/src/travel.ts`) are a deterministic generator over a real list of
airports, cities and neighbourhoods. Prices move with distance, cabin and
season; the same query returns the same result. No booking happens.

**Real:** the model, the protocol, the compiler, the renderer, the MCP
transport, the managed agent, and every screenshot in the README.
