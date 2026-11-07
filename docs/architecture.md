# Architecture

The claim this repository is built to test:

> A generative interface is a *protocol*, not a feature of one app. Write the
> component catalog once, let the agent compose every screen from it, and the
> same surfaces should draw in your own app, in someone else's client, and
> under whichever agent runtime you feel like running today.

Everything below is how that is arranged, and where it isn't true and why.

If you have not read the [README](../README.md), start there: it explains the
problem this shape exists to solve. This document assumes you want the
engineering. What travels over the wire is in [transport.md](transport.md).

---

## 0 · Seven words, before any diagram

Everything here is built out of seven ideas. Each is simpler than its name.

**Component.** One piece of interface the app already knows how to draw — a
flight card, a date picker, a price summary. The app ships the code for it. The
agent never sends code, only the *name* of a component and what to put in it.

**Catalog.** The list of every component the app has, with the exact inputs each
one takes, written as JSON Schema. `catalogs/a2ui-travel/catalog.json` is ours:
33 components, the A2UI v1.0 basic set plus fifteen travel ones. It is the
vocabulary — the agent can say anything the catalog lists and nothing it does
not.

**Surface.** One screen's worth of interface, with an id. The card under a reply
is a surface (`inline-1`); the panel down the side is a surface (`sidebar`); the
home screen is a surface (`home`). Surfaces are addressed by id, so the agent can
update one without touching the others.

**Data model.** A little store of values attached to a surface, addressed by
path — `/trip/startDate`, `/flights/0/price`. Components do not usually hold
their own values; they hold a *binding*, which is a path into this store. Change
the store and everything bound to it redraws, with no round trip to the model.
This is the piece that makes "draw the layout first, fill it in later" work at
all.

**Express.** A compact shorthand for writing a tree of components, so the model
does not have to emit verbose JSON:

```
head = Text("### Flights to London")
root = Column([head])
```

Roughly half the size of the JSON it compiles to, and a half-written Express
block can be read as it streams, so a surface paints while the model is still
typing. The A2UI SDK reads it (`A2uiRequestProcessor`); nothing in this
repository parses Express itself.

**Macro.** A named template the model can call like a component —
`Flights(...)`, `Stays(...)`, `Highlights(...)`, `Itinerary(...)`,
`Trip(...)` — expanded by the SDK's `MacroExpander` into ordinary catalog
components before anything is sent. A macro is pure layout over data the host
publishes; it never carries values of its own.

**Skill.** The document that teaches the model all of the above: which
components and macros exist, what each takes, and how to write Express. It is
*generated* by the SDK's `SkillGenerator` from the same processor the server
parses the model with, so it can never describe a component that does not
exist.

Put together, one turn reads: the agent writes **Express** naming
**components** and **macros** from the **catalog**, the server reads it with the
SDK and sends A2UI messages addressed to a **surface**, the client draws them,
and values flow through the **data model** — all of it taught by the **skill**.

---

## 1 · One build, many places

A small number of things are written once. Everything else is a thin adapter
around them.

```
                 ┌────────────────────────────────────────────┐
                 │   data/          the facts                  │
                 │   prompts/*.md   what the agent is told      │
                 │   catalog.json   the vocabulary (33 pieces)  │
                 │   examples/*.json  worked examples (source)  │
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
 │  Express ⇄ A2UI    │   │  renderers/        │   │  skills/*/SKILL.md │
 │  the SDK processor │   │  react/  flutter/  │   │  what the model    │
 │  and decompiler    │   │  travel views for  │   │  is told           │
 │  (a2ui-agent-sdk)  │   │  the official SDKs │   │                    │
 └─────────┬──────────┘   └──────────┬─────────┘   └───────────┬────────┘
           │                         │                         │
 ══════════╪═════════════════════════╪═════════════════════════╪════════
           │      consumed, never reimplemented, by            │
 ┌─────────▼───────────────┬─────────▼──────────┬──────────────▼────────┐
 │ apps/server/…/brain     │ apps/web           │ renderers/flutter     │
 │ skills, tools, the trip │ the React client   │ the second client,    │
 │ record, the canvas      │ (3 flows)          │ the same messages     │
 ├─────────────────────────┼────────────────────┼───────────────────────┤
 │ apps/server/…/doors     │ /catalog           │                       │
 │ interactions · live ·   │ every component,   │                       │
 │ http                    │ drawn by the SDK   │                       │
 └─────────────────────────┴────────────────────┴───────────────────────┘
```

**One brain, two doors, two renderers.** The server is two packages and the
split is load-bearing. `brain/` holds every decision worth making — the skills
the model is given, the tools it may call, the record a trip is kept in, the
canvas that mirrors what each renderer holds — and imports no transport.
`doors/` holds transport and nothing else: the typed door
(`doors/interactions/`, the Gemini Interactions API, answered over SSE), the
voice door (`doors/live.py`, the Gemini Live API, over a WebSocket), and the
HTTP app that mounts them (`doors/http.py`). The same conversation can be had
through either door, which is only true because neither knows anything the other
does not.

The rule that keeps it that way: when a door starts wanting to know what a trip
is, that knowledge belongs in the brain and the door should be asking for it.

**Python, because the SDK is Python.** The A2UI agent SDK — the Express
processor, the macro expander, the catalog resolver, the renderer state, the
skill generator — is the reference implementation. Using it directly means the
parser and validator in the path are the ones the protocol authors wrote, not
our reading of them. The Wire view's Express comes from the same SDK's
decompiler, over `POST /api/express`, so there is no second compiler anywhere.

**One configuration, three uses.** `brain/catalog.py` builds one
`A2uiRequestProcessor` from the catalog, the macros and the worked examples in
`catalogs/a2ui-travel/examples/*.json`. Its `prompt_snippet` is what the model
is taught, its parser is what the model is read with, and
`SkillGenerator(PROCESSOR.format)` writes the skills another agent loads. A test
asserts the skills on disk match what that generator writes, so the three cannot
drift.

**The catalog is the single source of truth.** `scripts/build_catalog.py` is the
only file you edit to add a component; `npm run generate` regenerates the
catalog JSON, every `SKILL.md`, the catalog reference the web app shows, and
the renderer fixtures the Flutter tests read. `npm run check` fails CI if any
drifts.

**What the model is told is a file, not a string in code.** The tool
descriptions live in `data/tools.json`; the agent's role and the per-surface
briefs live in `prompts/*.md`. Both doors read the same files, because a
retyped prompt is a different agent, and two agents with different manners is
a bug nobody can see in a diff.

There is one thing the catalog does not generate: **the trip model** — what a
trip *is*, which fields block which goals, and what each hop of a route still
wants. It is shared by the agent, the tools, the prompt and the data the panels
bind. See [The trip is a model](#the-trip-is-a-model-not-a-bag-of-keys).

---

## 2 · The three flows

They are properties of *where an answer goes*, not of this codebase, which is
why the same three exist in the React client and in the Flutter one.

| Flow | Surface id | Lifetime | What it composes |
| --- | --- | --- | --- |
| **inline** | `inline-{n}` per turn | appended, never replaced | one job — a picker, a summary, an action that continues the conversation |
| **sidebar** | `sidebar` (singular) | drawn once, then kept current by data | the record of what is settled, hop by hop, with Change on each decision |
| **home** | `home` (singular) | drawn when asked for | where the trip stands today, read first, not in reply to anything |

Singular ids are what make a panel a panel rather than a feed. Each surface has
its own brief (`prompts/surface-inline.md`, `surface-sidebar.md`,
`surface-home.md`), so the model knows that a 340 px column wants fewer, denser
rows than the conversation does.

A turn may create only its own surface and the standing panels (`Drawing`'s
`creatable`); it may update any surface the renderer already holds. Inline ids
are numbered past the highest one the renderer reports holding, so an answered
card is never overwritten.

---

## 3 · The interaction model

### Editing is not deciding

| | Components | What a change does |
| --- | --- | --- |
| **Editors** | Slider, CheckBox, ChoicePicker, TextField, DateTimeInput, DateRangePicker, TravelerCounter, AirportPicker | writes the data model, sends nothing |
| **Decisions** | Button, and tappable cards — FlightOption, HotelCard, ActivityItem | sends an A2UI action, which is the next turn |

A turn per interaction would make choosing an airport, a date and a party size
three turns, each answered with a *new* surface that knows nothing of the other
two. So: **one thing to choose → tappable cards, no button**; picking the flight
is the answer. **More than one → editors and one button**; the traveller sets
them all and presses once. Editors carry no action, and the prompt tells the
model which is which.

### The answer travels in the data model

A surface that asks the traveller something is created with
`sendDataModel=true`. Its renderer then reports that surface's data model on
every request, as `a2uiRendererDataModel` metadata, beside the A2UI v1.0 action
for whatever was pressed ([transport.md](transport.md)). That is A2UI's own
mechanism, and every renderer already implements it.

The server keeps a mirror of what it sent (`Canvas.wire`), so what the traveller
*changed* is a diff: `Canvas.edits` compares the reported `trip` against the
mirror, and what differs is recorded on the trip before the model is asked
anything. A value typed into a control is a fact; it does not wait on the model
noticing it and calling `save_trip`.

The server does not repair a surface the model drew. If a surface asks for
`/trip` fields and was not created with `sendDataModel`, or asks a date in a
text box, `brain/controls.py` says so to the model once, as advice, and the
model fixes it with an update. The surface is the model's; the check is the
host's.

### One turn, one job

The agent is instructed to lead — never end a turn without moving the trip on.
The panel is instructed to be read-only. On a panel turn those two
contradict, and a model resolves the contradiction by drawing the next step's
controls in the panel. So the "do this next" directive is scoped to inline
turns. The panel turn gets the sidebar brief and is told only to draw the
record.

### The conversation decides; the panel remembers

Two places that can change the same value leave the transcript with no record of
which one did — "when did the dates become the 19th?" has no answer. So the
split is absolute: **every editor lives inline**, and the panel is read-only.

Its one interaction is **Change**, which does not edit anything. The press is a
v1.0 action on a standing surface, and the server tells the model what it means
here (`presses.describe_action`): release that decision and ask for it again
inline, pre-filled. The model calls `release_decision`, and `release()` clears
the decision and whatever was decided because of it — a new date range releases
the flight priced against it, because a flight that looks settled and is priced
for dates nobody holds is worse than no flight. The dependency map is one level
deep and only where the dependency is real; cascading further would wipe an
hour's work because someone moved a date by a day.

The panel is **entirely A2UI the model composed**, usually with `Trip(...)`,
bound to `/panel`. The model draws it **once**: after the first turn that
settles a destination, if the renderer holds no `sidebar`, the server runs a
short panel turn (`doors/interactions/panels.py`). From then on every decision
reaches it as `updateDataModel` on `/panel`, `/plan` and `/trip`, with no model
turn and no redraw. This replaces rebuilding or replaying the panel when the
trip changes shape: the shape is in the data, so the surface never needs
drawing again. Opening the same session in the Flutter renderer draws the same
panel, and there is no travel-specific client code to port.

### The model owns the surface; the host owns the data

The host never rewrites what the model wrote. Its part is data. When a surface
binds a root the host owns, the host fills it on that surface and keeps it
current (`brain/data.py`, `Canvas.provide`):

| Root | Holds | Scope |
| --- | --- | --- |
| `/trip/...` | the record, field by field | every surface that binds it |
| `/places/origins`, `/places/destinations` | the airports this deployment flies, as `AirportPicker` options | every surface |
| `/panel` | the trip hop by hop, as `Trip()` draws it | every surface |
| `/plan` | every decision, as labelled rows | every surface |
| `/days` | the saved day plan, as `Itinerary()` draws it | every surface |
| `/money` | committed, budget, remaining, with the currency | every surface |
| `/booked` | every chosen fare, in hop order, as `Booked()` draws it | every surface |
| `/flights`, `/hotels`, `/highlights` | the rows the last lookup returned | the cards this turn draws or updates |
| `/fares/N`, `/rooms/N` | hop N's own rows, from a search made with `hop: N` (else the latest), as `Flights(hop=N)` and `Stays(hop=N)` bind them | the cards this turn draws or updates |

Three rules make that safe:

- **Only what is bound.** A root goes to a surface only if one of its components
  binds it, and `/trip` goes field by field, only the fields the surface binds
  (`trip_fields_bound`). A card about dates is not sent the hotel.
- **Only what changed.** Every value is compared against the wire mirror, which
  holds both what was sent and what the traveller has since set, so nothing is
  sent twice and an edit is never overwritten by the value it replaced.
- **The model's suggestions stand.** If the model created a surface with a
  starting value of its own (`$/trip/startDate = "2027-04-12"`), the host leaves
  it alone until the record itself moves.

### An answered surface goes grey

Only the newest surface accepts input. Everything above it answered a message
the conversation has moved past; clicking it would answer a settled question.
Spent surfaces stay on screen as the record of what was chosen and get `inert`
plus a greyscale filter — the greying matters, because a control that looks live
and does nothing is worse than one that looks finished.

### The trip is a model, not a bag of keys

The trip model (`apps/server/src/travel_a2ui/brain/trip/`) is the schema, and it
is the only definition. The agent, the tools, the prompt and the data roots all
read it, so dates have one format, a picker's `["economy"]` reaches a tool as
`"economy"`, and "is this priceable yet" has one answer.

It carries five things:

- **`FIELDS`** — what a trip is made of: each field's key, the kind it holds, and
  how to name it when asking a person for it. Declared in
  `data/trip-model.json` rather than in code.
- **`normalize` / `coerce`** — the only way values get in. They coerce the shapes
  a real interface produces: a picker's single-item array, an RFC 3339 instant
  from a date input, `"$2,600"` typed into a text field.
- **`missing_for` / `can_do`** — "can this be priced yet", answered once for
  everyone. The tool gate and the prompt both call it.
- **`DECISIONS`** — the fields that are *decisions* rather than refinements. A
  decision is something the traveller settled and can press Change on. A cabin
  preference, a neighbourhood or a ceiling on the nightly rate refines a
  decision already made.
- **`journey`** — the route hop by hop, with what each hop has and what it still
  wants.

It reads one file and does nothing else — no network, no database — because it is
imported by the server, the tools and a test suite alike, and a golden file
(`apps/server/tests/goldens/trip.json`) pins its output across trips chosen for
the decisions they force.

### The agent leads, and finishes

A planner that answers questions is a search box with better manners. So the
agent is expected to end every turn having moved the trip on or having asked
exactly what it takes to.

**What it must not be is a ladder.** A fixed sequence of stages works until
somebody says *"a friend joins us in Chicago and comes back with us"* — three
hops, two party sizes, one needing a hotel and one not — and no ordering of
stages describes that. So the judgement is the agent's. `DECISIONS` is written
in the order things are usually settled, but it is a list for reading, not a
sequence anything is held to. What the host provides instead is facts:

- **`journey(trip)`** walks the route and reports, per hop, what that hop still
  wants — dates, who is on it, a ticket if it is flown, somewhere to stay *only
  if somebody sleeps there*, something to do *only if they stay more than a
  night*. Facts in travelling order, with no opinion about which gap matters
  most and nothing invented: a hop nobody recorded does not appear, including
  the way home.
- **`prompts/flow.md`** holds the judgement — the loop, and a table of gap →
  step → tool → components. **`prompts/journey.md`** holds how a route is read,
  including noticing that it ends somewhere other than home. Both are markdown
  people edit on purpose, so a change to how the agent decides is a reviewable
  diff rather than a code change.

The panel's `/panel` rows are computed from the same `journey()`
(`data.panel_rows`), so the panel cannot disagree with what the agent thinks is
left.

**Real trips bend**, and two fields are how:

- **`skip`** — what this trip does not need. Driving rather than flying, staying
  with family, no fixed budget. Skipped counts as settled and is never asked
  about again, which is the difference between a planner and a form. A trip
  that does not come back says `oneWay`.
- **`legs`** — the route after the first stop. Each leg carries its own dates,
  its own origin when it is not simply the previous stop, its own party size when
  that differs, its own ticket, its own stay, and a `mode` when the hop is not
  flown at all.

The party size is where a simpler model quietly gets the answer wrong:

> SFO to New York with two nights in Chicago for a wedding, then home — two
> tickets back, because a friend is coming with me.

That is one trip, three legs, two party sizes and a return that is not a mirror
of the outbound. With a single `travelers` the way home is priced for one person
and the friend has no seat, silently. `stops()` resolves each leg against the
trip and the leg before it — an omitted origin means "from wherever I just was",
an omitted party size means "same as the rest" — so nothing downstream
reimplements those defaults, and `party_varies()` tells the interface when the
difference is worth showing. The agent records the whole route in one
`save_trip` and then asks only for the dates.

That resolution is also what makes a price correct. A fare is quoted per person,
so a hop with three on it is three tickets, and a room rate is per night, so six
nights is six of them. The tools return `perUnit`, `units`, `total` and a
`priceLabel` computed from the *hop's* party rather than the trip's — "$412 each
· $1,236 for 3" — and the total is carried in the trip's one currency, because a
euro rate summed into dollars is a number nobody can act on.

The nights are the other multiplier, and they decide more than the arithmetic. A
hop that lands and leaves the same day wants no hotel and no day plan; a hop that
stays four nights wants both, and they are two separate answers — "I'm at my
sister's" settles the bed and nothing else, and the four days are still empty.

### `/trip` is shared; everything else is per-surface

This is the fix for "it forgot what I told you", and it is structural rather
than a prompt instruction.

```
  the trip (durable, server-side)
        │  updateDataModel, field by field, to every surface that binds it
        ▼
  surface data model  →  /trip/startDate, /trip/origin, /trip/travelers, …
        │  reported as a2uiRendererDataModel on every request,
        │  diffed against the mirror, recorded before the model sees the turn
        ▼
  the trip
```

A `DateRangePicker` bound to `$/trip/startDate` shows the agreed date without
the model typing it out. What the traveller sets there comes back with the next
request and is recorded because the host recorded it, not because the model
remembered to call `save_trip`. Change the route on an inline card and the panel
moves in the same response, with no model in the path.

---

## 4 · What the agent may not assume

An agent that invents an input produces a real-looking answer to a question
nobody asked. Two inputs matter most:

- **Dates.** A model in a hurry prices "a sample week in April" and shows the
  fares as if they were the traveller's.
- **Where they are.** A default airport, or one guessed from a time zone, puts
  a fare from JFK in front of someone in Atlanta.

Prompt rules are not enough, so the tools enforce it: `search_flights`,
`search_hotels` and `estimate_cost` answer with what they `needs` and an
instruction to ask, rather than with numbers. `flexible: true` is the deliberate
way through for "roughly what does Madrid cost in April", and what comes back is
labelled indicative. `save_trip` refuses a range that ends before it starts.

The departure airport is **asked, never inferred**: the opening surface draws an
`AirportPicker` bound to `$/places/origins`, the airports this deployment
actually flies. The client sends its calendar day and locale (`client.today`,
`client.locale`) and nothing about where it is.

The per-turn prompt names the fields still missing rather than dumping the trip
as JSON, because a model asked to infer what is absent tends to fill the gap in
itself.

Every surface showing a price states what it is priced against — route, dates,
party size — in its heading. `LHR → Madrid · 12–19 Apr · 3 travellers`, not
`Flights to Madrid`.

---

## 5 · A turn, end to end

### The first one is the slow one, and that is fixable

Worth saying before the diagram, because it is the turn everybody judges the app
on. The Interactions API is **stateful**: `previous_interaction_id` carries the
whole prior context on Google's side, so the system instruction — role, flow,
journey, inventory, controls, data roots, the processor's catalog snippet, about
fifteen thousand tokens — is sent once when a conversation starts and never
again.

That makes the first turn about eight times slower to draw than the second
(`tools/eval/latency.py`, same ask, same model):

    cold     firstWord 5.3s   firstSurface 19.6s   done 29.4s
    second   firstWord 1.8s   firstSurface  2.4s   done 15.0s
    warmed   firstWord 5.2s   firstSurface 11.6s   done 13.5s

So `POST /api/warm` starts the conversation against a throwaway turn, and the
client fires it when somebody **first focuses the composer** — the earliest
honest signal they are about to type, and several seconds before they finish.
The traveller's first message is then a *second* turn.

Focus rather than page load, deliberately: a warm-up on load spends a model call
on everyone who reads the page and leaves. And it is only possible because
`build_prompt_parts` splits the prompt by what varies — the stable half has no
surface id, no trip and no date in it, so nothing warmed early is stale by the
time somebody types.

```
 client                     server                       Gemini
 ──────                     ──────                       ─────────
 POST /api/chat  ─────────▶ inbound.read()  — v1.0 messages,
 a2ui + metadata            │                 validated by the SDK
 + surfaces                 │  1. reconcile the mirror with what
                            │     the renderer holds; record the
                            │     press and the edits (Canvas.edits)
      ◀── SSE: ui ──────────┤  2. surfaces catch up with the record
                            │     (Canvas.provide → updateDataModel)
                            │  3. stable prompt half + volatile half
                            ├──── interactions.create ─────▶
                            │◀─── text deltas ─────────────┤
                            │  4. Drawing: the SDK processor's
                            │     open_stream splits prose from
                            │     <a2ui> blocks; macros expanded;
                            │     each message applied to the
                            │     wire mirror before it is sent
      ◀── SSE: text ────────┤   prose, as it arrives
      ◀── SSE: ui ──────────┤   the card, bound to /flights, empty
                            │◀─── function_call ───────────┤
      ◀── SSE: tool ────────┤  5. the lookup runs; its rows go to
      ◀── SSE: ui ──────────┤     /flights on this turn's surface,
                            │     and the card fills in
                            ├──── results (rows summarised) ▶
                            │  6. refused block / advice / a
                            │     promise with nothing drawn:
      ◀── SSE: retry ───────┤     told to the model, once each
      ◀── SSE: resume ──────┤  7. the receipt for the next turn
      ◀── SSE: done ────────┤
      ◀── SSE: ui ──────────┤  8. no panel yet? a panel turn
 MessageProcessor
 the surface renders
 the traveller taps a card
      ──── next turn ──────▶  { version: "1.0", action: { name: "select_flight",
                                surfaceId: "inline-2", context: { id: "IB6250" } } }
```

The decisions in there that are load-bearing:

**What the traveller set is recorded before the model is asked.** The press and
the diffed edits go through the same validation `save_trip` uses
(`model.sieve`), field by field, so a bad value is refused without losing the
rest. The model is *told* about anything refused, because otherwise it reads
back the old trip and nothing in it says a value was turned away.

**The stable half of the prompt comes first, and that is the whole
optimisation.** The skill is thousands of tokens and identical on every turn of
a conversation; the trip state is a few dozen and changes constantly. Ordering
them stable-then-volatile is the difference between paying for the catalog once
per conversation and once per message, which is why there is a test asserting
the order rather than trusting it.

**Prose and UI are split server-side, as the model streams, by the SDK.**
`A2uiRequestProcessor.open_stream` yields text parts, A2UI parts and error
parts; a partial block yields the messages it can already stand behind, so a
surface materialises progressively instead of appearing at the end. Each A2UI
part is checked twice: against the *drafted* mirror (what the model wrote,
macros and all) by the processor, and against the *wire* mirror (what the
renderer will hold, macros expanded, over the full catalog) with the SDK's
`RendererState`. A message that would not apply on the wire never leaves the
server.

**The interface is drawn before the data exists.** The *shape* of an answer is
known before the answer is: a list of fares is a list of fares before you know
what is in it. So the prompt asks the model to draw `Flights(...)` first —
bound to `/flights`, which is empty — and then call `search_flights`. When the
rows land, the host sends them as one `updateDataModel` and the card the
traveller is already looking at fills in. The components are sent once; only
the data model moves. The model is then told the card is on screen and filled,
so it does not draw it again.

```
flights = Flights("LHR → Madrid · 12–19 Apr · 3 travellers")
root = Column([flights])
```

**A block that is refused is told to the model, once, and never rewritten.** The
SDK's reason and the offending block go back as the next message, and the model
writes it again. Once, because a model that cannot fix it on the second attempt
will not fix it on the fifth and the traveller is waiting. The host does not
patch the surface itself: an interface that the model did not write is not the
model's interface.

**A turn is a sequence of parts, not "prose then UI".** A model says a sentence,
draws, and says another. Rendering all the prose above all the surfaces puts
"want me to hold one?" above the thing being held, so the parts interleave in
arrival order. Each tool round starts a new text part, because two sentences
separated by a tool call are two paragraphs.

**Pressing is a turn, and the wire carries an A2UI action, not a sentence.** A
tap produces a v1.0 action message (`name`, `surfaceId`, `sourceComponentId`,
`timestamp`, `context`), which is what *any* A2UI renderer produces when someone
presses something. The server turns it into a sentence for the model, because
how *this agent* interprets a tap on a read-only panel is a fact about this
agent, not about the tap. A renderer that refuses a message reports it as a
v1.0 error, and the model is told `[renderer] <code> on surface "<id>": …` so it
can redraw what could not be shown.

**A voice call draws the same way.** The Live API has no text channel to stream
Express on, so in a call the model draws through a tool, `render_a2ui_express`.
Each call is read by the same processor and the same mirror as a typed turn, and
a block with no `surface(...)` line becomes a new `voice-N` card.

**A reload is a new conversation.** The session id is generated per page load, so
reloading clears the transcript and the trip — which is what a person means by
reloading a demo. The key does persist; losing that would be a more annoying
kind of forgetting. Sessions live in memory with an idle expiry and a cap on how
many can be live at once. Each turn ends with a `resume` receipt the client
hands back, so a turn that lands on an instance that has never seen the session
still continues the same Gemini conversation with the same trip.

---

## 6 · Where the API key lives

Nowhere on the server. The browser holds it, sends it in `x-goog-api-key` on
each request, and the server passes it to the SDK and forgets it. It is never
written to any session, never logged, and never put in a URL — a key in a
query string lands in every access log between the browser and the edge.

`#key=…` in the fragment is the supported way to hand one over, because a
fragment is never sent to a server. `?key=…` also works and the app takes it,
strips it from the address bar, and then tells you plainly that the server saw
it and to rotate it.

For a shared deployment that does not want to ask, a `GEMINI_API_KEY` in the
environment is used when the header is absent.

---

## 7 · Testing, and what is simulated

| Layer | How |
| --- | --- |
| Trip model | coercion from real interface shapes, readiness, what each hop still wants, what was ruled out, a three-leg route with two party sizes; pinned by `goldens/trip.json` |
| Reading the model | `apps/server/tests/test_interactions.py`: a scripted model through the real turn — surfaces paint before the turn ends, rows fill a card drawn before the lookup, refused blocks and advice go back once, the panel is drawn once and then kept current by data |
| Renderer → agent | v1.0 actions, errors, capabilities and data models, validated with the SDK's models; malformed ones reported, never defaulted |
| Examples | every Express block in the README, `docs/`, the quickstart and `prompts/` is read through the real pipeline (`test_docs_examples_compile.py`); every JSON example validates (`test_examples.py`) |
| Skills | the skills on disk equal what `SkillGenerator(PROCESSOR.format)` writes |
| Catalog | every component the catalog offers has a React view and a Flutter one, and the basic ones are the SDK's own |
| Web app | `tools/e2e/chat.mjs`, `interaction.mjs`, `frameworks.mjs`, `keys.mjs`, `sample.mjs` — a real browser against the real server with a scripted model |
| Flutter | `flutter test`, against fixtures the real pipeline writes (`scripts/build_fixtures.py`), and `tools/e2e/flutter.mjs` in a browser |
| The agent itself | `tools/eval/live.mjs` and `tools/validate/` — scenarios against the real model, graded mechanically off the event stream. Not in CI; they cost real money |
| Freshness | `npm run check` fails if the catalog, the skills, the catalog reference or the renderer fixtures drift |

None of the CI suites needs an API key.

### The goldens

`apps/server/tests/goldens/` holds three files: the trip model's output across a
set of trips, the tools' wording, and the fixture provider's answers. Over code,
a golden is an alarm for a change nobody intended. The rule that makes one worth
having: **check the golden fails when you break the thing it pins.** A golden
nobody has watched fail is a file, not a test.

### Where the data comes from

Travel data arrives through `TravelProvider`
(`apps/server/src/travel_a2ui/brain/providers/types.py`). The one that ships is
`FixtureProvider`, a deterministic generator over the rows in `data/` — CSV and
JSON, read from disk at startup, with real geography in it: every airport
carries a latitude, a longitude and a region, so a fare is a floor plus a rate
per great-circle kilometre, a flight time is taxi and climb plus cruise, and a
connection is a hub the carrier actually has, within a quarter of the direct
distance of the route. London to Paris is nonstop-only; San Francisco to Tokyo
connects at Los Angeles rather than Denver. The same query returns the same
result.

Every answer carries its own `provenance`, so a surface can say where its
numbers came from without anyone having to remember to add it. Destination
guidance is real; fares, schedules and hotels are not, and the UI says so. No
booking happens.

### The contract, and why it is shaped like that

A data function that cannot say *I don't know* says something else instead:
flights under $1 come back as an empty list under a heading that says flights;
flights to Reykjavik come back to an airport code made of its first three
letters. So the contract makes not-knowing the only alternative to knowing. A
provider answers `Found` or `NotFound`, and `found()` raises rather than build a
success with nothing in it. A filter that matches nothing is widened one
constraint at a time and the surface says which; a place the provider cannot
identify is a refusal that names the cities it does know. A rough question may
be answered without a departure city, but the provider has to name the one it
sampled from.

**Real:** the model, the protocol, the SDK in the path, the renderers, and every
screenshot in the README.
