# Architecture

The claim this repository is built to test:

> A generative interface is a *protocol*, not a feature of one app. Write the
> component catalog, the compiler and the renderer once, and the same surfaces
> should draw in your own app, in someone else's chat client, and under whichever
> agent runtime you feel like running today.

Everything below is how that is arranged, and — as importantly — where it isn't
true and why.

If you have not read the [README](../README.md), start there: it explains the
problem this shape exists to solve. This document assumes you want the
engineering.

---

## 0 · Six words, before any diagram

Everything here is built out of six ideas. Each is simpler than its name.

**Component.** One piece of interface the app already knows how to draw — a
flight card, a date picker, a price summary. The app ships the code for it. The
agent never sends code, only the *name* of a component and what to put in it.

**Catalog.** The list of every component the app has, with the exact inputs each
one takes, written as JSON Schema. `catalogs/a2ui-travel/catalog.json` is ours:
30 components. It is the vocabulary — the agent can say anything the catalog
lists and nothing it does not.

**Surface.** One screen's worth of interface, with an id. The card under a reply
is a surface (`inline-1`); the panel down the side is a surface (`sidebar`); the
home screen is a surface (`home`). Surfaces are addressed by id, so the agent can
update one without touching the others.

**Data model.** A little store of values attached to a surface, addressed by
path — `/trip/startDate`, `/flights/0/price`. Components do not usually hold
their own values; they hold a *binding*, which is a path into this store. Change
the store and everything bound to it redraws, with no round trip to the server.
This is the piece that makes "draw the layout first, fill it in later" work at
all.

**Express.** A compact shorthand for writing a tree of components, so the model
does not have to emit verbose JSON:

```
head = Text("Flights to London", variant="h3")
root = Column([head])
```

About a third the tokens of the JSON it compiles to, and — crucially — a
half-written Express program is still a valid program, so a surface can be
compiled and painted while the model is still typing.

**Skill.** The document that teaches the model all of the above: which
components exist, what each takes, and how to write Express. It is *generated*
from the catalog rather than written by hand, so it can never describe a
component that does not exist.

Put together, one turn reads: the agent writes **Express** naming
**components** from the **catalog**, the server compiles it to A2UI messages
addressed to a **surface**, the client draws it, and values flow through the
**data model** — all of it taught by the **skill**.

---

## 1 · One build, many places

A small number of things are written once. Everything else is a thin adapter
around them.

```
                 ┌────────────────────────────────────────────┐
                 │   data/          the facts                  │
                 │   prompts/*.md   what the agent is told      │
                 │   catalog.json   the vocabulary (30 pieces)  │
                 └───────────────────┬────────────────────────┘
                                     │  generated from
                 ┌───────────────────┴────────────────────────┐
                 │  scripts/build_catalog.py   ← edit here     │
                 │  scripts/build_skills.py    (SDK generator) │
                 └───────────────────┬────────────────────────┘
                                     │
           ┌─────────────────────────┼─────────────────────────┐
           │                         │                         │
 ┌─────────▼──────────┐   ┌──────────▼─────────┐   ┌───────────▼────────┐
 │  Express ⇄ A2UI    │   │  renderers         │   │  skills/*/SKILL.md │
 │  the SDK's parser  │   │  React (packages/) │   │  what the model    │
 │  (Python) and our  │   │  Flutter (apps/)   │   │  is told           │
 │  port (TypeScript) │   │                    │   │                    │
 └─────────┬──────────┘   └──────────┬─────────┘   └───────────┬────────┘
           │                         │                         │
 ══════════╪═════════════════════════╪═════════════════════════╪════════
           │      consumed, never reimplemented, by            │
 ┌─────────▼───────────────┬─────────▼──────────┬──────────────▼────────┐
 │ apps/server  (Python)   │ apps/web           │ apps/mcp-view         │
 │ the agent, the tools,   │ the React client   │ the same renderer,    │
 │ the trip, MCP, voice    │ (3 flows)          │ for an MCP host       │
 └─────────────────────────┴────────────────────┴───────────────────────┘
 ┌─────────────────────────┬────────────────────┬───────────────────────┐
 │ apps/worker  (retiring) │ apps/flutter_client│ apps/gallery          │
 │ the original TypeScript │ the second client  │ static showcase       │
 └─────────────────────────┴────────────────────┴───────────────────────┘
```

**Two servers, for now.** `apps/server` is Python and is the one that ships;
`apps/worker` is the original TypeScript implementation, still deployed, being
retired once the cutover is verified. They implement the same agent, which makes
the interesting risk *silent disagreement* rather than breakage — so every layer
where they could disagree is pinned by a golden file. See
[§9](#9--testing-and-what-is-simulated).

**Python, because the SDK is Python.** The A2UI agent SDK — the Express parser,
the catalog loader, the skill generator — exists in exactly one language, and it
is the reference implementation. Using it directly means the compiler in the
path is the one the protocol authors wrote, not our reading of it. The
TypeScript port remains, checked against the same goldens; compiled against a
non-trivial surface — bindings, a `_template` row, an `Event` carrying bound
context — the two agree on every field.

**The catalog is the single source of truth.** `scripts/build_catalog.py` is the
only file you edit to add a component; `npm run generate` regenerates the
catalog JSON, the fixtures, the compiled examples and every `SKILL.md`. `npm run
check` fails CI if any drifts, so "the docs are stale" is not a state this
repository can be in.

**What the model is told is a file, not a string in code.** The tool
descriptions live in `data/tools.json`; the agent's role and the per-surface
briefs live in `prompts/*.md`. Both servers read the same files. That is not
tidiness — a retyped prompt is a different agent, and two agents with different
manners is a bug nobody can see in a diff.

There is one thing the catalog does not generate: **the trip model** — what a
trip *is*, which fields block which goals, and what to ask for next. It is
shared by the agent, the tools, the prompt and the panels. See
[The trip is a model](#the-trip-is-a-model-not-a-bag-of-keys).

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
| 3 | **A2UI inside an MCP App** — the app bundle carries its own A2UI renderer and draws payloads inside its sandbox | ✅ the `ui://` app template |

A single `tools/call` result carries a text summary, the pattern-1 payload, and
the pattern-3 shell. A host takes whichever it understands and ignores the rest;
a host that understands neither still gets a usable sentence. `?view=payload`
and `?view=html` drop one or the other for a host that knows what it wants.

Pattern 3 is the one that does the work today, because almost no host renders
A2UI natively yet. Pattern 1 is the one worth having, because the moment a host
does, the same server gets better without redeploying: the payload was always
there.

### Pattern 3, and the mistake that made it render nothing

The first implementation returned a `text/html` resource in every tool result
and assumed the host would draw it. It did not, and the plugin ran the tools and
showed a blank panel.

A host does not look inside a tool result for HTML. It looks for a `ui://`
resource declared in `resources/list` with `mimeType: "text/html;profile=mcp-app"`,
reads it **once per conversation** as a template, and then forwards each tool
result to that template over a postMessage bridge. The template is an MCP client
in its own right: it sends `ui/initialize`, waits for the host's capabilities and
theme, sends `ui/notifications/initialized`, and only then receives
`ui/notifications/tool-result` — which is where the surface is, under
`structuredContent`. A view that renders before that handshake shows nothing,
because nothing has arrived yet.

Three things have to line up, and the absence of any one of them looks identical
from the outside:

| | Here |
| --- | --- |
| the template | `ui://travel-a2ui/surface`, with its CSP in `_meta.ui` |
| the link | every tool carries `_meta.ui.resourceUri` naming it |
| the surface | `structuredContent`, which is what the host forwards |

Because the template is fetched once rather than per call, it has the whole
renderer **inlined** — which is what makes `resourceDomains: []` possible, and a
view that fetches nothing cannot be broken by a content policy. That also
resolves the tension that produced the shell: the objection was 230 kB *per tool
call*, and a template is not per call.

`tools/e2e/mcp.mjs` plays the host's side of that handshake in a real
`sandbox="allow-scripts"` iframe, in the right order, so the failure cannot come
back quietly.

### The legacy shell, in detail

`?view=legacy` returns the older MCP-UI shape for a host that reads those: a
`text/html` resource per tool result, about 450 bytes, with the payload inlined:

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
them all and presses once. Editors do not call `runAction`, and the prompt tells
the model which is which.

### The answer travels in the action, and the server guarantees it

A commit button carries a *context* — the paths it is sending, resolved against
the data model — which is A2UI's own mechanism for submitting a form and the one
thing every renderer already does without being taught.

It used to work differently, and worse. The browser kept a snapshot of each
surface as it arrived, diffed it against the live data model on every change,
and turned the result into a sentence: `[interface] search_flights (origin:
"JFK")`. A hundred lines of recursive tree comparison, a synthetic prose format
nothing parsed, and a bar counting "3 unsent changes" — all of it invented here,
none of it in the protocol, and therefore none of it present in the Flutter
client, which shipped the dead end instead.

What survives is the guarantee, moved to where it holds for everyone.
`bindCommitContext` runs on the server after a surface compiles:

- every path the surface's editors write to is bound into its commit buttons,
  under the model's own key where it named one;
- a surface with editors and **no** button at all gets one, attached to its root.

The model is still asked to bind them, because it picks better key names than an
algorithm splitting on slashes. It just no longer has to be right.

### One turn, one job

A rule worth stating because getting it wrong was invisible from the code and
obvious from a live run: **the panel turn and the inline turn are told different
things**.

The agent is instructed to lead — never end a turn without moving the trip on.
The panel is instructed to be read-only. Both reasonable; together, on a panel
turn, contradictory. The model resolved it the way a model does: it advanced the
plan, in the panel, with the controls the next step needed. The host ignored
them, so nothing broke, and the panel showed three dead controls.

So the "do this next" directive is scoped to inline turns. A panel turn is told
plainly that advancing the plan is not its job this time, and what is
outstanding is given as context rather than as an instruction.

### The conversation decides; the panel remembers

The panel used to carry controls, which meant two places could change the same
value and the transcript had no record of which one did — "when did the dates
become the 19th?" had no answer. So the split is now absolute: **every editor
lives inline**, and the panel is read-only.

Its one interaction is **Change**, which does not edit anything. It *releases*
the decision — clearing it, and whatever was decided because of it — and the
agent re-opens it in the conversation, pre-filled with what was there. A new
date range releases the flight priced against it, because a flight that looks
settled and is priced for dates nobody holds any more is worse than no flight.
`release()` owns that dependency map, one level deep and only where the
dependency is real; cascading further would wipe an hour's work because someone
moved a date by a day.

The host enforces it rather than asking: an interaction on a non-inline surface
is never treated as an answer, whatever component produced it, so a model that
draws a slider in the panel produces something inert rather than a second way to
change the trip.

The panel is also, now, **entirely A2UI**. It used to be half-and-half: an A2UI
surface on top, and underneath a React checklist and a key/value dump of the
trip, both reading the trip model directly. They worked well and they were the
one part of the panel a mobile client could not draw, because they were not in
the protocol at all.

The checklist is composed from catalog components now and bound to `/plan`,
which the server publishes and keeps current — so the agent decides the shape
once and the rows move as the trip moves, without a model turn. Each row arrives
with its line already composed (`✓ Dates`, `→ Flight`, `– Somewhere to stay —
not needed`), because a template row is a single component and cannot declare
children inline. Opening the same session in the Flutter renderer draws the same
panel, and there is no travel-specific client code left to port.

### The server owns the data model

Surfaces read trip facts from `/trip`, and until recently the browser put them
there: `seedTrip` filled each new surface as it arrived, `syncTrip` pushed
changes into the standing panels, both walking a list of field names compiled
into the client. Correct, fast, and the reason the web app was the only client
that could behave properly — a second client would need the same list, and again
every time the trip grew a field.

The server says it in the protocol's own words instead:

| | Message | For |
| --- | --- | --- |
| A new surface | `createSurface.dataModel` | complete when it first paints, never blank-then-filled |
| A standing panel | `updateDataModel` | the sidebar and home screen, as the trip changes |

A spent inline card is deliberately excluded. It is the record of what was asked
at the time, and rewriting history underneath it is worse than letting it be
old.

### An answered surface goes grey

Only the newest surface accepts input. Everything above it answered a message
the conversation has moved past; clicking it would answer a settled question
against a data model describing a trip that no longer exists. Spent surfaces
stay on screen as the record of what was chosen and get `inert` plus a
greyscale filter — the greying matters, because a control that looks live and
does nothing is worse than one that looks finished.

### The trip is a model, not a bag of keys

The trip model is the schema, and it is the only definition. Before it existed
the agent, the tools, the prompt and the browser each had their own opinion
about what a trip was, and every bug worth reporting came out of that gap: dates
in two formats, `cabin` arriving from a picker as `["economy"]` and reaching a
tool expecting `"economy"`, "is this priceable yet" answered three different
ways, two copies of the field list drifting apart.

It carries four things:

- **`FIELDS`** — what a trip is made of. Twenty-one fields across seven stages,
  each with the kind it holds and how to name it when asking a person for it.
  They are declared in `data/trip-model.json` and read by both servers, so the
  two cannot hold different opinions about what a trip is.
- **`normalize`** — the only way values get in. It coerces the shapes a real
  interface produces: a picker's single-item array, an RFC 3339 instant from a
  date input, `"$2,600"` typed into a text field.
- **`missingFor` / `canDo`** — "can this be priced yet", answered once for
  everyone. The tool gate, the prompt and the UI all call it.
- **`plan`** — the trip as a sequence of steps, which is what makes the agent
  lead instead of wait.

It reads one file and does nothing else — no network, no database — because it
is imported by a Python server, a Cloudflare Worker, a browser bundle and a test
suite alike. It exists twice, once in each language, and a golden file holds the
two to the same answers: 9 trips chosen for the decisions they force, every
function's output pinned.

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
 client                     server                       Gemini
 ──────                     ──────                       ─────────
 POST /api/chat  ─────────▶ run_turn()
 x-goog-api-key             │
 + action or message        │  1. commit what the traveller set
                            │     on screen — before asking the
                            │     model anything
                            │
                            │  2. build the system prompt:
                            │     role + skill + surface brief
                            │     (stable half first, so the
                            │     catalog is cached)
                            ├──── interactions.create ─────▶
                            │
                            │◀─── text deltas ─────────────┤
                            │
                            │  3. ExpressStream splits prose
                            │     from <a2ui> blocks and
                            │     recompiles the open block
                            │
      ◀── SSE: text ────────┤   prose, as it arrives
      ◀── SSE: ui ──────────┤   partial surface, then done
                            │
                            │◀─── function_call ───────────┤
                            │
      ◀── SSE: ui ──────────┤  4. the SKELETON: the layout for
                            │     this answer, bound and blank
      ◀── SSE: tool ────────┤     …the tool runs…
      ◀── SSE: ui ──────────┤  5. the FILL: only the data model
                            ├──── results, all in one ─────▶
                            │
      ◀── SSE: ui ──────────┤  6. the panels, brought up to date
      ◀── SSE: done ────────┤
 store.apply(messages)
 the surface renders
 the traveller taps a card
      ──── next turn ──────▶  { name: "select_flight",
                                context: { id: "IB6250" } }
```

Six decisions in there are load-bearing:

**What the traveller set is committed before the model is asked.** A value typed
into a control is a fact. Depending on the model to notice it and call
`save_trip` is what made a second card forget what the first one asked, so the
host records it directly. The model is *told* about anything it refused, because
otherwise it reads back the old trip and nothing in it says a value was turned
away.

**The stable half of the prompt comes first, and that is the whole
optimisation.** The skill is thousands of tokens and identical on every turn of
a conversation; the trip state is a few dozen and changes constantly. Gemini
caches a repeated prefix implicitly, so ordering them stable-then-volatile is
the difference between paying for the catalog once per conversation and once per
message. Swapping the halves produces a correct prompt, a correct demo, and a
much larger bill — which is why there is a test asserting the order rather than
trusting it.

**Prose and UI are split server-side, as the model streams.** The model emits one
text stream containing both; the splitter separates them and recompiles the
partial Express block on every chunk, so a surface materialises progressively
instead of appearing at the end. Doing it in the browser would mean shipping raw
Express to the client and rendering it as prose for a few hundred milliseconds —
exactly the bug the first version of the e2e test caught.

**The interface is drawn before the data exists.** The moment the agent chooses
`search_flights`, the *shape* of the answer is known: four cards, each with an
airline, a time, a price. So the layout goes out immediately — `createSurface`,
a data model seeded with four blank rows, `updateComponents` — and the real rows
arrive into it when the tool returns. The components are sent **once**; only the
data model moves. Nothing recompiles, and the card the traveller is looking at
is not replaced underneath them.

The pending state needs no new protocol: a binding whose path does not resolve
is *pending*, and one resolving to `""` is *empty*. That is why the blank rows
are `{}` and not rows of empty strings — seed the wrong one and every card
paints as a flight with no airline and no price, which is worse than a spinner
because it looks like an answer.

**A turn is a sequence of parts, not "prose then UI".** A model says a sentence,
draws, and says another. Rendering all the prose above all the surfaces puts
"want me to hold one?" above the thing being held, so the parts interleave in
arrival order. Each tool round starts a new text part, because two sentences
separated by a tool call are two paragraphs — concatenated they read as
`…anything.Nothing nonstop is showing`, which looks like a typo.

**A block that does not compile is told to the model.** Express written wrong
used to end the turn with a hole where a surface should be, and nothing ever
said so. Now the compile error and the offending block go back as the next
message and it rewrites them — once, because a model that cannot fix it on the
second attempt will not fix it on the fifth and the traveller is waiting.

**Clicking is a turn, and the wire carries an action rather than a sentence.**
A tap produces `{ name, surfaceId, context, dataModel }` — which is what *any*
A2UI renderer produces when someone presses something, with nothing taught to
it. It used to be a sentence the browser composed (`[interface] search_flights
(origin: "JFK")`), which was a private protocol wearing the costume of a user
message: the Flutter client, which does not compose that sentence, simply
did not work. The server turns the action into a sentence for the model, because
how *this agent* interprets a tap on a read-only panel is a fact about this
agent, not about the tap.

**A reload is a new conversation.** The session id is generated per page load and
deliberately not persisted, so reloading clears the transcript and the trip —
which is what a person means by reloading a demo. The key does persist; losing
that would be a more annoying kind of forgetting. Sessions live in memory with a
24-hour idle expiry and a cap on how many can be live at once, so the abandoned
session each reload leaves behind goes away instead of accumulating.

---

## 7 · The MCP server

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

## 8 · Where the API key lives

Nowhere on the server. The browser holds it, sends it in `x-goog-api-key` on
each request, and the Worker passes it to the SDK and forgets it. It is never
written to any session, never logged, and never put in a URL — a key in a
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

## 9 · Testing, and what is simulated

| Layer | How |
| --- | --- |
| Trip model | coercion from real interface shapes, readiness, the plan, skipped stages, and a three-leg route with two party sizes |
| Compiler | 20 golden cases byte-checked against the reference Python compiler |
| Skill generator | output byte-identical to the reference generator |
| Renderer store | bindings, checks, templates, surface lifecycle |
| MCP server | real JSON-RPC through the handler, not unit calls into helpers |
| Agent loop | scripted model output through the real stream splitter, asserting *order*: that a surface paints before the turn ends, the skeleton goes out before the tool and the fill after it |
| Web app | `tools/e2e/chat.mjs` — a real browser, a real turn, 14 assertions |
| The agent itself | `tools/eval/live.mjs` — 10 scenarios against the real model, graded mechanically off the event stream. Not in CI; it costs about $2 a run |
| Interaction model | `tools/e2e/interaction.mjs` — editing sends nothing, committing sends everything as an A2UI action, spent surfaces go inert, the panel stays read-only and holds no React, 21 assertions |
| MCP app | `tools/e2e/mcp.mjs` — a live server, a sandboxed iframe, 24 assertions |
| Data providers | the contract, and each of the four ways the code it replaced answered a question it could not answer |
| Two implementations | six golden files, described below |
| Freshness | `npm run check` fails if the catalog, the fixtures, the examples, the skills or any golden drifts |

461 TypeScript tests, 294 Python tests for the server, 16 for the build tooling,
71 browser assertions across three end-to-end runs, and a live evaluation of the
agent. None of them needs an API key.

### The goldens

Two servers implementing one agent makes the dangerous failure *silent
disagreement* rather than breakage: both answer, both draw, and only the details
differ. So each layer where that could happen is pinned to a file the TypeScript
writes and the Python must reproduce exactly — the fixtures' output, the trip
model, the tools' wording, the whole system prompt, the compiled skeleton, and
the four passes over a surface.

The rule that makes them worth having: **write the golden from the incumbent
before porting, then check the golden fails when you break the port.** A golden
nobody has watched fail is a file, not a test. Following it found nine
divergences in the tool layer, a 32-bit arithmetic bug, an iteration-order
difference between a JavaScript `Set` and a Python `set` that changed the keys
of a button's payload — and two bugs that were in the *original*, where a
faithful port was the only reason they surfaced at all.

### Where the data comes from

Travel data arrives through `TravelProvider`
(`apps/server/src/travel_a2ui/providers/`), and
the deployment picks the implementation: fixtures by default, Amadeus when
`AMADEUS_CLIENT_ID` and `AMADEUS_CLIENT_SECRET` are set. There is no
`PROVIDER=live` flag to go with them, because a flag can be set without a
credential and the deployment then fails on a traveler's screen rather than at
configuration time.

Every answer carries its own `provenance`, so a surface can say where its
numbers came from without anyone having to remember to add it — and on a live
deployment the forecast card reads *Sample data* while the fares beside it do
not, because Amadeus has no weather product and the fixture's provenance travels
with the delegated answer.

**Fixtures** are a deterministic generator over the rows in `data/` — CSV and
JSON. The Python server reads them from disk; the Worker cannot, having no
filesystem, so `scripts/build_fixtures.py` compiles the same rows into its
bundle. Prices move with distance, cabin and season; the same
query returns the same result. Destination guidance is real; fares, schedules
and hotels are not, and the UI says so. No booking happens.

### The contract, and why it is shaped like that

The provider interface exists because the code before it was called directly by
the tools, under a comment promising you could "swap these functions for real API
calls and nothing above them changes". That was an assertion rather than a seam,
and it hid four ways to answer a question with something untrue:

| Asked | Answered |
| --- | --- |
| Flights under $1 | an empty list, under a heading that said flights |
| Flights to Reykjavik | four flights to **REY**, an airport code taken from the first three letters |
| Hotels in Reykjavik | four **Madrid** hotels in Lavapiés, priced in euros, captioned "4 stay(s) in MAD" |
| Anything at all | no indication anywhere that the numbers were invented |

All four are one bug: a function that could not say *I don't know* said something
else instead. So the type makes not-knowing the only alternative to knowing.
`Found.items` is `[T, ...T[]]`, which cannot be `[]` — an empty success is
unrepresentable, and the compiler enforces it rather than a reviewer. A filter
that matches nothing is widened one constraint at a time and the surface says
which; a place the provider cannot identify is a refusal that names the cities it
does know. A rough question may be answered without a departure city, but the
provider has to name the one it sampled from.

**Real:** the model, the protocol, the compiler, the renderer, the MCP
transport, and every screenshot in the README.
