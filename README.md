# Travel A2UI

**A travel agent that answers in interfaces.** You describe a trip in your own
words; it replies with flights you can pick, dates you can set, and a day plan
you can tap through — built fresh each turn, not chosen from a set of screens
somebody designed in advance.

> **This is a sample application, not an official Google project.** A2UI — the
> protocol, the specification and the component catalogs it builds on — is the
> work of [the A2UI project](https://github.com/google/a2ui). This repository is
> an independent app built on top of it, and is not affiliated with or endorsed
> by Google LLC. Treat it as a worked example of how to build and deploy a
> generative-UI application, not as a reference implementation of the protocol.

<p align="center">
  <img src="docs/screenshots/02-mcp-light.png" alt="Flight options rendered as A2UI components" width="820">
</p>

---

## Start with the problem

Say this out loud:

> *"I want to go from San Francisco to London and back, for two of us."*

That took you three seconds. Now try to do it on a travel website.

You will fill in a departure airport, an arrival airport, a date, another date,
a number of travellers, a cabin class. Six fields, and you have only just
described the *shape* of the trip. You have said nothing about what you actually
want — that you would rather not land at midnight, that one of you is joining
from Chicago, that you are flexible by a day either way if it saves a few
hundred, that there is a wedding on the Saturday so the hotel has to be near the
church.

Here is the uncomfortable part: **there is no form that could have asked you all
of that.** Not because nobody has tried, but because trips do not have a fixed
shape.

- One person wants a weekend in Lisbon.
- Another wants San Francisco → Chicago → New York → home, two nights in the
  middle, a different number of people on the last leg because a friend is
  coming back with them.
- Another is driving, and only needs somewhere to stay.
- Another has a fixed budget and wants to know what fits inside it.

Every one of those is a different set of questions, in a different order, with
different things that matter. A form has to guess the questions in advance and
show the same ones to everybody. So it guesses the most common trip, and
everyone whose trip is not that one ends up fighting the form, opening six tabs,
and doing the actual planning in a spreadsheet or a group chat.

**The input problem and the output problem are different problems, and they need
different answers.**

---

## Why chat alone is not the answer either

Chat fixes the input. You can say anything, in any order, and change your mind
halfway through. Open-ended input is exactly right for something with infinite
variations.

But chat is a genuinely bad way to *receive* an answer. Read this:

> Option 1 is Iberia IB612 departing 07:15 arriving 19:40 with one stop in
> Madrid for $624. Option 2 is United UA930 departing 15:20 arriving 09:55
> nonstop for $811. Option 3 is Virgin Atlantic VS20 departing 19:00 arriving
> 13:15 nonstop for $779. Option 4 is...

Nobody compares four flights that way. By the third one you have forgotten the
first. There is nothing to sort, nothing to click, and no way to say "that one"
without typing out the flight number and hoping you copied it correctly.

And there is a second, quieter problem. When you say *"me and my partner, first
week of June, somewhere warm"*, the agent has understood **something** — but you
cannot see what. Did it hear two people or two rooms? Which first week of June?
Warm meaning Lisbon or warm meaning Bali? In a pure chat interface you find out
three turns later, when it prices the wrong trip.

So:

|  | Good at | Bad at |
| --- | --- | --- |
| **A form** | Showing you exactly what it understood | Asking an open-ended question |
| **Chat** | Asking an open-ended question | Showing you exactly what it understood |

You need both halves. **Open-ended in, structured out.**

---

## What generative UI actually is

Here is the whole idea, with no jargon:

> Normally a programmer decides in advance what every screen looks like, and the
> program picks one. In generative UI, **the AI builds the screen as part of its
> answer**, out of a box of pieces the app already knows how to draw.

Think of it like a box of LEGO. The app ships the bricks: a flight card, a date
picker, a price summary, a counter for how many people are going. The app does
*not* ship instructions for a finished model. Each turn, the AI decides which
bricks this particular answer needs and clicks them together.

That is why it can handle a trip nobody anticipated. It is not choosing from
five pre-built screens — it is building the screen that this answer needs, from
the same bricks, every time.

Three things follow from that, and they are the reason this is worth doing:

**1. You can see what it understood.** You said "two of us, first week of June".
It draws a traveller counter showing **2** and a date range showing **1–7 June**.
If it heard you wrong, you can see it immediately and drag the dates — instead of
discovering the mistake three turns later.

**2. You answer by pointing, not by typing.** Four flights arrive as four cards.
You tap one. No flight numbers, no copying, no "the second one, no sorry the
third".

**3. It stays a conversation.** You can still say *"actually, can we leave a day
later?"* at any point, because the text box never went away. The interface is
the *answer*; your own words are still the question.

### The loop

```
        you speak or type, in your own words
                        │
                        ▼
        the agent works out what you meant
                        │
                        ▼
        it builds a small interface that shows
        what it understood and what it found
                        │
                        ▼
        you press, drag, pick — or just say
        something else
                        │
                        └──────────► back to the top
```

Every turn the understanding gets more exact, and you never had to learn a form.

---

## Why this matters beyond travel

Travel is the example. The pattern underneath it is not about travel at all.

**It gives people back their evenings.** Planning a trip for four people across
three cities is currently a spreadsheet, a group chat, eleven browser tabs, and
two hours. Most of those two hours are not decisions — they are re-entering the
same dates into a fourth website. Generative UI collapses the re-entering and
leaves the deciding, which is the part you actually wanted to do.

**It makes plans people can share.** A trip that lives as a structured plan —
rather than as scattered messages and screenshots — is a thing you can send to
the person coming with you. They can see what is settled, what is still open,
and what it costs. Half of what makes group travel exhausting is that nobody has
the same picture of the plan; this gives everyone the same picture.

**It reaches people a form never could.** Forms assume you know the vocabulary:
airport codes, cabin classes, "flexible dates ±3". Speaking plainly is something
everyone can do — including in their own language, including out loud, including
if typing is hard for them. Then the interface does the precise part, so nobody
has to be precise in order to be understood. That is a genuine widening of who
gets to use software well.

**And it generalises.** Anything where the request is open-ended and the answer
is a decision has this shape: choosing a health plan, filing something with a
government, picking a mortgage, booking care for a parent. All of those are
badly served by forms for the same reason travel is — the situations vary more
than any form can anticipate — and all of them are decisions people currently
make from paragraphs of text they cannot compare.

The prize is not "a prettier chatbot". It is software that adapts to the person
rather than making the person adapt to the software.

---

## How this repository solves it

Now the real version of the idea, still in plain language.

**The agent writes the interface; it does not send pictures.** When the agent
decides you should see four flights, it does not produce HTML or an image. It
writes a short description of a UI tree — which components, in what order, bound
to which data. That description travels over the network and *your* device draws
it, using components your device already has.

That one decision is what makes everything else possible: the same answer can be
drawn by a web page, a phone app, or Claude, because each of them knows how to
draw the bricks and none of them needs to know anything about travel.

**The language it writes is A2UI.** [A2UI](https://a2ui.org) is an open protocol
for exactly this — agents that reply with interfaces. It defines the message
shapes ("create a surface", "here are its components", "here is its data") and
leaves the components themselves to a *catalog* the app supplies. Our catalog is
`catalogs/a2ui-travel/catalog.json`: 30 components, including `FlightOption`,
`HotelCard`, `DateRangePicker` and `ItineraryDay`.

**It writes them in a shorthand called Express.** Raw A2UI is JSON, which is
verbose to generate. A2UI Express is a compact notation for the same tree:

```
head = Text("Flights to London", variant="h3")
row  = FlightOption($airline, $departTime, $arriveTime, $origin, $destination,
                    $price, Event("select_flight", {id: $id}))
list = List(_template($/flights, row))
root = Column([head, list])
```

About a third of the tokens of the equivalent JSON, and — this is the part that
matters for how it *feels* — **a half-written Express program is still a valid
program.** So the interface can be compiled and painted while the model is still
typing the rest of it, instead of appearing all at once at the end.

**The screen fills in before the data arrives.** When the agent decides to search
for flights, the *shape* of the answer is already known: four cards, each with an
airline, a time, a price. So the layout is drawn immediately — bound, blank, and
shimmering — and the real numbers stream into it when the search returns. You
watch an interface fill in rather than a spinner spin.

**Nothing is invented.** The tools that fetch travel data cannot return an empty
success. If there are no flights under your price cap, the tool widens the search
and *says which filter it dropped*. If it has never heard of your destination, it
says so and offers ones it knows, rather than inventing an airport code. Every
price on screen carries a note saying where the number came from. See
[Notes on the parts that are simulated](#notes-on-the-parts-that-are-simulated).

### The shape of the system

```
   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
   │  React web   │   │ Flutter web  │   │ Claude, via  │
   │    client    │   │    client    │   │  MCP plugin  │
   └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             │   A2UI messages — the same ones,
                             │   whichever is on the other end
                    ┌────────┴─────────┐
                    │   Python server  │
                    │                  │
                    │  · the agent     │  ← decides what to say and draw
                    │  · the skill     │  ← teaches the model the catalog
                    │  · the tools     │  ← flights, hotels, weather, costs
                    │  · the trip      │  ← what has actually been decided
                    └────────┬─────────┘
                             │
                  ┌──────────┴──────────┐
                  │  Gemini             │
                  │  · Interactions API │  typed conversation
                  │  · Live API         │  spoken conversation
                  └─────────────────────┘
```

Three ways to see it, two ways to talk to it, one server that decides what the
interface is. The clients contain no travel logic at all — a client knows how to
draw a `FlightOption` and nothing about what a trip is.

**You can switch the runtime and watch the same components come back.** The app
offers two agent frameworks as an explicit choice: the Interactions API (typed)
and the Live API (spoken, with a microphone). They are genuinely different
runtimes, sharing no code path. That they produce the same surfaces is the
clearest available evidence that the interface layer is independent of the
engine behind it.

---

## Where to read next

Start wherever matches what you want:

| If you want to… | Read |
| --- | --- |
| Type the demo and see it work | **[docs/demo-script.md](docs/demo-script.md)** — exact things to type, and what should come back |
| See every component, drawn | **[docs/catalog.md](docs/catalog.md)** — each one pictured beside the line of Express that made it |
| Understand the flows and the edge cases | **[docs/user-flows.md](docs/user-flows.md)** — including which rules are enforced in code rather than asked of the model |
| Understand how it is built | **[docs/architecture.md](docs/architecture.md)** — the long version, decision by decision |
| Use it inside Claude | **[docs/install-in-claude.md](docs/install-in-claude.md)** — the plugin, and what it carries |
| Deploy it | **[docs/deploying.md](docs/deploying.md)** — Cloudflare and Cloud Run, and the one setting not to change |

---
## Run it

One server. It is Python, it is two packages — `brain/` and `doors/` — and it
serves the API, the MCP endpoint and the built clients from one origin.

### The Python server

```bash
git clone <your-repo> && cd travel-a2ui
npm run setup                        # installs, regenerates, builds, tests
pip install -e ./apps/server         # the server and its dependencies

# terminal 1 — the API
uvicorn travel_a2ui.doors.http:app --port 8080 --app-dir apps/server/src --reload

# terminal 2 — the React client, with hot reload
npm run dev:web                      # http://127.0.0.1:5173
```

Open `http://127.0.0.1:5173` and paste a Gemini API key when asked. Once the
client is built (`npm run build`), the server serves it too and one port is
enough:

```
http://127.0.0.1:8080
```

### The Worker

```bash
npm run dev:worker       # http://127.0.0.1:8787 — API, MCP and the built app
```

### The key

Paste it when asked, or skip the form entirely:

```
http://127.0.0.1:8080/#key=AIza...
```

The key is taken out of the URL and the address bar is rewritten before anything
else reads it, then kept in this browser and sent with each request. It is never
stored on the server. `#key=` is the form to use: a fragment never leaves the
browser. `?key=` also works, because people paste it, but the server saw it and
the app says so once — treat such a key as logged. (Get one at
[aistudio.google.com/apikey](https://aistudio.google.com/apikey).)

The **Catalog** tab works with no key at all — every component the agent can
draw, rendered by the real renderer, so it is the fastest way to see A2UI render
with nothing else in the path.

### Deploy it

Either server serves the API, the MCP endpoint and the built web app from one
origin — one deploy, one URL, no CORS to configure.

**Cloud Run** (the Python server) builds from the `Dockerfile` at the repository
root: Node builds the clients in one stage, Python runs them in the next. Run
[`.github/workflows/cloudrun.yml`](.github/workflows/cloudrun.yml)
from the Actions tab with four settings in place:

| Setting | What it is |
| --- | --- |
| `GCP_PROJECT_ID` *(variable)* | The Google Cloud project to deploy into |
| `GCP_REGION` *(variable)* | e.g. `us-central1` |
| `WIF_PROVIDER` *(secret)* | A Workload Identity provider, so no service-account key is ever stored |
| `WIF_SERVICE_ACCOUNT` *(secret)* | The account it impersonates — needs Cloud Run Admin, Artifact Registry Writer and Service Account User |

Every push to `main` deploys. This was manual while the Cloudflare Worker still
held the public URL — two deploys racing to serve the same users is how a demo
becomes unexplainable — and with Cloud Run as the deployment that reason is
gone. The live service is
[travel-a2ui-vy7stnte2a-uc.a.run.app](https://travel-a2ui-vy7stnte2a-uc.a.run.app),
and it serves all of it: the React client at `/`, the Flutter client at
`/flutter`, the agent API, and the MCP endpoint at `/mcp`.

**[docs/deploying.md](docs/deploying.md)** has the one-time setup for both
targets — including the `gcloud` commands that create the Workload Identity
pool, and why its `attribute-condition` is not optional.

One detail worth knowing before you scale it: the service runs with
`--max-instances 1`, and that is a correctness constraint rather than a cost
one. Conversations live in the server's memory — nothing is written to disk,
which is what "we do not store your conversation" has to mean if it means
anything — so a second instance would hold a second set of conversations, and a
traveller whose next request landed on it would find their trip gone. Raising
the limit means giving the sessions somewhere shared to live first.

**Cloudflare** (the Worker) — the original backend, now superseded by the
Python server and kept only until it is removed:

```bash
npx wrangler login
npm run deploy
```

Or push to `main` with `CLOUDFLARE_API_TOKEN` (the "Edit Cloudflare Workers"
template) and `CLOUDFLARE_ACCOUNT_ID` set, and
[`.github/workflows/deploy.yml`](.github/workflows/deploy.yml)
does it. Tests run first; a red build does not deploy.

By default every visitor brings their own key. To run a shared deployment on one
key instead, set `GEMINI_API_KEY` — as a Cloud Run environment variable, or a
Worker secret — and the app stops asking.

---

## Make it something else

Nothing here is coupled to travel except the names, and the fastest way to see
that is to replace them. In rough order of effort:

**Swap the catalog.** `catalogs/a2ui-travel/catalog.json` is the vocabulary: one
JSON Schema entry per component. Add `InvoiceLine` beside `FlightOption`, write
the React function in `packages/renderer/src/components/`, register it, and the
model can draw invoices. [`docs/catalog.md`](docs/catalog.md) is generated from
that file — every component pictured as the renderer actually draws it, with the
one line of Express that produced it — so it is also the shape to copy.

**Narrow what the model sees.** `catalogs/a2ui-travel/agent-components.json` is
the allow-list. Renderers keep their full registry; only the *prompt* is pruned,
so trimming it costs a client nothing and saves tokens on every single turn.

**Regenerate the skill.** `npm run generate` runs the official A2UI
`SkillGenerator` over the pruned catalog and writes `skills/`. You do not write
the component documentation the model reads — the catalog is the source, and a
component you add documents itself.

**Change the tools.** `data/tools.json` is one array of
`{name, description, input_schema}`, and `brain/tools.py` is one `switch` over
it. The contracts are provider-neutral on purpose: `gemini_tools()` is a
six-line adapter and `mcp_data_tools()` is another, so a second protocol costs
six lines rather than a second copy of the schemas.

**Then the parts you should not need to touch**: the compiler, the renderer, the
streaming split, the commit binding, the panel plumbing. Those are the A2UI
layer, and they do not know what a trip is.

Two rules are worth stealing whatever you build. Anything that must not vary
belongs in the host, not the prompt — a rule in a prompt is a request to a model,
and a rule in the host is a guarantee. And anything derivable should be derived:
a night count written by the model is correct in the screenshot and wrong the
moment a date moves.

---

## The three flows

Not three screens — three *placements*, each answering a different question, and
each composing the same data differently. They are properties of where an answer
goes, not of this codebase, which is why they survive the trip into an MCP host.

### 1 · Inline — attached to the message being answered

The user asked something; this is the answer, drawn under it.

- **Scope**: one job. Three flights, not nine. A date picker, not a settings
  panel.
- **Lifetime**: permanent and per-turn. Surface `inline-3` stays live and
  clickable after the conversation moves past it, so you can go back and change
  your mind.
- **Actions continue the conversation.** Picking a flight is the user's next
  turn, phrased in the interface instead of in prose.
- **User flow**: *"Find me a flight to Madrid"* → three `FlightOption`s → tap one
  → the agent saves it and asks about hotels.

### 2 · The panel — what is settled

Persistent, beside the conversation. **Read-only**, and that is the design
rather than a limitation.

- **Scope**: decisions, not controls. The route stop by stop, the flight and
  stay chosen, the dates, what it comes to, how far through the plan you are.
- **Lifetime**: singular and replaced. Writing to `sidebar` again rebuilds it;
  it is not a feed. Values sync from the trip with no model in the path, so
  changing the route on an inline card updates it immediately.
- **One interaction: Change.** It releases that decision — and whatever was
  decided because of it — and the agent re-opens it *inline*, pre-filled. Two
  places that can edit one value is how a conversation loses track of its own
  history, so the conversation is where you decide and this is the record.
- **User flow**: press Change on the flight; it disappears from the panel and
  comes back as a picker in the conversation, with the fare you had highlighted.

### 3 · Home — where the trip stands today

Read first, and not in reply to anything.

- **Scope**: the number that matters most right now, then anything needing a
  decision, then context — weather, the map, the next day.
- **Lifetime**: singular, regenerated when the trip or the day changes.
- **Generative layout**: not a fixed dashboard. Ask it to "put the packing list
  on top" or "show the budget as a meter" and the layout changes, because the
  layout is the model's output.
- **User flow**: open the app in the morning → *17 days to Madrid*, budget used,
  the one unbooked thing → tap it and land back in the conversation.

| | Rendered in the app by | Composed for MCP hosts by |
|---|---|---|
| Inline | `apps/web/src/components/Chat.tsx` | `show_flight_options`, `show_hotel_options`, `show_itinerary`, `show_price_summary` |
| Sidebar | `apps/web/src/components/Sidebar.tsx` | `show_trip_controls` |
| Home | `apps/web/src/components/Home.tsx` | `show_trip_dashboard` |

**The same three flows are available over MCP.** Every placing tool takes a
`surface` argument (`inline` \| `sidebar` \| `home`), which changes what is
composed and where it is written — `sidebar` and `home` are singular surfaces
that replace themselves, inline ones are keyed per answer. So a plugin installed
in Claude gets the same product, not a subset of it.

<p align="center">
  <img src="docs/screenshots/03-dashboard-dark.png" alt="A generated trip dashboard in dark mode" width="820">
</p>

Two more tabs earn their place. **Catalog** shows every component the agent can
draw, with the exact signatures the model is given — so "what is it allowed to
use" is one click away rather than a JSON schema away.

<p align="center">
  <img src="docs/screenshots/05-catalog-dark.png" alt="The component catalog, with signatures" width="820">
</p>

**Wire** shows any live surface in both representations, the Express the agent
wrote and the JSON the host received, because "what did the model actually emit"
is the first question anyone asks about generative UI.

<p align="center">
  <img src="docs/screenshots/06-wire-light.png" alt="The same surface as Express and as A2UI JSON" width="820">
</p>

---

## Voice

Choosing **Gemini Live** as the agent framework puts a microphone in the
composer. The session is relayed through the server rather than opened straight
from the browser, and that choice is the whole architecture in miniature: the
browser *could* open the socket itself, and then every client would need the
catalog, the compiler, the tools and the trip. Instead it sends microphone bytes
and receives audio plus A2UI — exactly what the Flutter client sends
and receive.

Voice is a property of the *backend*, not of the client. Every client can speak
if the Live framework is selected; none of them contains any audio logic beyond
a microphone and a speaker.

The model is handed the same six `show_*` builders the MCP endpoint uses and
told to draw rather than read a list aloud. A live turn:

```
TOOL    save_trip {travelers: 2, startDate: 2027-04-12, …}
TOOL    show_flight_options {origin: JFK, destination: Madrid, …}
SURFACE mcp-flights: Text, FlightOption ×4, Text, Column
agent:  "…the cheapest is Delta for about 352, the fastest is TAP
         for around 362 nonstop."
```

It rounded the numbers, named two of four options, and left the rest to the
screen — which is what voice and a screen together are *for*. The relay shares
the session with the typed conversation, so saying "make it three of us" moves
the same panel.

Switching framework reloads the page and starts a fresh conversation with an
empty trip. Two APIs with two conversation histories is difference enough
without also deciding which parts of a half-made trip survive the crossing.

Three things cost an evening and are worth knowing if you build one:
`fetch` refuses a `wss:` URL (Workers upgrade over `https:`); the runtime
delivers inbound frames as a **Blob**, so `TextDecoder().decode` produces rubbish
and every frame vanishes without an error; and the Live API rejects an entire
`setup` if a function declaration carries `additionalProperties`, `$schema` or
`strict` — which ordinary Gemini tool schemas all do.

---

## How it fits together

**One brain, four doors, two renderers.** That sentence is the architecture, and
the directories are named after it.

```
                         ┌──────────────────────────────────────┐
data/          ─────────►│  brain/                              │
catalogs/      ─────────►│    skills   what the agent is told    │
prompts/*.md   ─────────►│    tools    what it can call          │
                         │    trip     what it remembers         │
                         │    surface  what every surface goes   │
                         │             through before it ships   │
                         └──────────────────────────────────────┘
                                          │
              ┌───────────────┬───────────┴───────────┬──────────────┐
              ▼               ▼                       ▼              ▼
      doors/interactions  doors/live            doors/plugin    doors/http
      Gemini              Gemini Live           MCP, for        mounts the
      Interactions API    API, spoken           Claude and      other three
      typed, over SSE     over a socket         other hosts     and serves
              │               │                       │         the clients
              └───────────────┴───────────┬───────────┘
                                          ▼
                                 A2UI JSON messages
                                          │
                          ┌───────────────┴───────────────┐
                          ▼                               ▼
                  packages/renderer                apps/flutter_client
                  React                            Flutter
```

The **brain** holds every decision worth making: the skills, the tools, the trip
record, the passes a surface goes through. It has no idea which door a request
came through, and nothing in it imports a transport.

The **doors** hold transport and nothing else. `interactions` is the reference
one; `live` is the same brain over a bidirectional audio socket; `plugin` is the
same brain answering MCP, where every call is self-contained; `http` mounts the
other three. When a door starts wanting to know what a trip is, that knowledge
belongs in the brain and the door should be asking for it.

The **renderers** draw A2UI, send actions back, and wait for the next A2UI.
Neither holds travel logic, catalog knowledge, or any opinion about what a trip
is — which is the whole test of whether this is really A2UI. The React renderer
core (`binding`, `store`, `checks`, `functions`) mentions a trip only in its
comments, and the Flutter client is a second implementation of the same
protocol rather than a port of the first.

That constraint is the one to defend when changing anything here: **maximise
server-side agency, minimise client-side logic, so one agent drives thin,
generic clients on Web, iOS, Android and Flutter.** A feature that needs new
client code to work is a feature that has left the protocol.

Everything the model is given is a file on disk rather than a string in code,
and that is deliberate. The tool descriptions live in `data/tools.json`, the
role and the surface briefs in `prompts/*.md`. Both servers read the same files,
so a change to what the agent is told is reviewable as a diff — and there is no
second, hand-typed copy to drift. A retyped prompt is a different agent, and the
difference does not look like a bug from either side.

Four things are generated and checked in, so a stale one fails CI rather than
shipping quietly:

| Generated | From | Regenerate |
|---|---|---|
| `catalogs/a2ui-travel/catalog.json` | the vendored upstream basic catalog + travel components | `python3 scripts/build_catalog.py` |
| `apps/server/src/travel_a2ui/brain/providers/fixtures.generated.py` | `data/` | `python3 scripts/build_fixtures.py` |
| `catalogs/a2ui-travel/examples/compiled/*.json` | the `.express` examples | `python3 scripts/build_examples.py` |
| `skills/**/SKILL.md` | the catalog, via the SDK's `SkillGenerator` | `python3 scripts/build_skills.py` |

`npm run generate` does all four; `npm run check` fails if any is stale, and
also checks the six goldens described under [Tests](#tests).

---

## The skills

A **skill** is the document that teaches the model the catalog: what components
exist, what each one takes, and how to write them. It is generated from
`catalog.json` by the A2UI SDK's own `SkillGenerator` rather than written by
hand, so a component added to the catalog is a component the model knows about
on the next build — and cannot describe one that is not there.

The design principle it implements is worth stating on its own:

> A skill's `name` and `description` are what an agent sees during discovery, and
> all it sees before deciding whether to load the thing. So they describe a
> **capability** — "generates interactive user interface components" — and never
> an implementation. Which inference format, which protocol version, which schema
> file: none of that helps a model route a request, and all of it crowds out the
> words that do. Those details go in `metadata`, where SDKs and humans can read
> them and the model pays nothing for them.

```
skills/
└── express-modular/
    ├── a2ui-core/SKILL.md                          the notation, which never varies
    └── a2ui-travel/SKILL.md                        this catalog's components
```

Three shapes used to be generated — this one, the same catalog as a single
Express skill, and the same interfaces as raw A2UI JSON — and you could switch
between them in the running app. The point was to answer "what is Express
actually buying you" by measurement rather than by argument, so it was measured
(`tools/eval/skills.py`, four asks, three samples each):

| Variant | drew the right component | compiled first time |
|---|---|---|
| `express-modular` | 11/12 | 10/12 |
| `express-monolithic` | 10/12 | 9/12 |
| `direct-json-monolithic` | 3/12 | 3/12 |

Direct JSON drew nothing at all on three of the four asks, and took longest
doing it. Between the two Express shapes, five more samples on the scenarios
where they differed put modular ahead again with no scenario going the other
way — so there is one shape now, and no picker for a question with one answer.
A generated sample of each retired shape is in `docs/skill-variants/`, and
`VARIANTS` in `scripts/build_skills.py` is one line: put a shape back and re-run
the evaluation whenever a new model makes the question live again.

The modular shape is also what scales past one domain: an agent working on
travel loads `a2ui-core` + `a2ui-travel` and never pays for the charting
catalog.

**These generated skills are half the contract.** They say what components exist
and how to emit them. What the agent does *when* — which step comes next, how a
route with three hops and two parties is shaped, which control a decision is
asked in — is authored markdown in `prompts/`, because it is judgement rather
than a catalog.

No skill ships a script. They are instructions, and a test asserts that each
directory contains nothing but `SKILL.md`.

---

## A2UI Express

The notation the agent writes:

```
surface("inline-flights")
$/trip/selectedOutbound = ""
heading = Text("Outbound · JFK → MAD · Sun 12 Apr", variant="h3")
f1 = FlightOption("Iberia", "18:40", "08:15 +1", "JFK", "MAD", "$412",
                  Event("select_flight", {id: "IB6250"}),
                  duration="7h 35m", stops="Nonstop", badge="Cheapest")
root = Column([heading, f1])
```

Three properties make it worth a compiler:

- **It is about a third the tokens of the equivalent JSON.** The Wire tab prints
  the exact ratio for whatever is on screen.
- **A partial program is still a program.** `root = Column([heading, f1])` is
  valid the moment those lines exist, so the surface paints while the model is
  still typing. Truncated JSON is a parse error.
- **Variables are ids.** The model does not have to invent an id for every
  nested component and then remember it.

[`packages/express`](packages/express) is a TypeScript port of the reference
implementation in [google/a2ui](https://github.com/google/a2ui) — lexer, parser,
compiler, decompiler and a streaming front end, with no ANTLR runtime, so it fits
in a Worker.

**It is diffed against the original.** Twenty cases in `tools/parity/cases` are
compiled by both this and Google's Python compiler and asserted equal. When they
disagree, the golden is right and the port is wrong. Same story on the Python
side: `skillgen`'s signature output is asserted byte-identical to the reference
prompt generator's.

```bash
pip install a2ui-agent-sdk
python3 scripts/gen_parity.py          # regenerate the goldens
npx vitest run packages/express        # 64 tests, including all 20 parity cases
```

---

## The MCP app: the same UI, inside Claude

`POST /mcp` is a stateless Streamable-HTTP MCP server whose tools return
interfaces rather than text. It is the fourth modality and the one that reaches
furthest: the three flows above, drawn by the same React components, inside
someone else's chat app.

**[docs/install-in-claude.md](docs/install-in-claude.md)** is the step-by-step —
Claude Code, Claude Desktop, and claude.ai. The short version:

```bash
claude mcp add --transport http travel-a2ui https://travel-a2ui-vy7stnte2a-uc.a.run.app/mcp
```

### What comes back from a tool call

Three things, so that nothing degrades to nothing:

| Part | For | Size |
| --- | --- | --- |
| a plain-text summary | the model, and any host that can't draw | a line |
| `application/vnd.a2ui+json` | a host with its own A2UI renderer | ~2–6 kB |
| a `text/html` shell | every other host, rendered in an iframe | **~450 B** |

The shell is not the renderer. It is the payload inlined, plus a `<script src>`
pointing back at the deployment the host just called — so the 220 kB React
bundle is fetched once and cached, instead of riding along on every tool call
and eating the host's result budget each time. The origin comes from the request
URL, so a production deploy, a preview and `wrangler dev` each serve their own
with nothing configured (`?origin=` overrides it, for a tunnel or a proxy).

A host that renders A2UI natively can drop the HTML with `POST /mcp?view=payload`;
an HTML-only host can drop the payload with `?view=html`.

### Composed on the fly, not a menu of cards

Eight tools, and the split matters:

- `show_flight_options`, `show_hotel_options`, `show_trip_controls`,
  `show_itinerary`, `show_trip_dashboard`, `show_price_summary` — shortcuts for
  the six layouts that come up most, composed from the catalog server-side.
  Fast, deterministic, no second model in the path. Each takes
  `surface: inline | sidebar | home`, so the three flows are available in Claude
  exactly as they are in the web app.
- `get_a2ui_component_reference` → `render_a2ui_express` — **the actual
  capability.** The first returns the generated output contract: the grammar,
  the streaming rules, and the positional signature of all 40-odd components.
  The model reads it once, writes A2UI Express for the layout *this*
  conversation needs, and the second compiles it and hands back a surface drawn
  by the same components. Compile errors come back naming exactly what was
  wrong — including an invented component name, with the list of real ones — so
  a second attempt can fix it.

The reference is a *tool* and not only a prompt on purpose: hosts surface MCP
prompts as something the user must invoke by hand, so a model that can only read
prompts can never learn the vocabulary mid-conversation. As a tool it can.

<p align="center">
  <img src="docs/screenshots/05-mcp-view.png" width="46%" alt="A flight picker rendered from an MCP tool result">
  <img src="docs/screenshots/05-mcp-view-composed.png" width="46%" alt="A layout composed on the fly from catalog components">
</p>

Left: `show_flight_options`. Right: a pre-flight card — price summary, budget
meter, checkbox, expense split — that no tool hard-codes; the model wrote it as
Express and `render_a2ui_express` compiled it. Both are screenshots from
`tools/e2e/mcp.mjs`, taken inside a `sandbox="allow-scripts"` iframe, which is
the strictest thing a host does.

Calling it directly:

```bash
curl -s localhost:8787/mcp -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
        "name":"show_flight_options","arguments":{"destination":"Madrid"}}}' | jq
```

---

## Layout

```
travel-a2ui/
├── data/                       the facts: destinations, airlines, lodging, tool contracts
├── prompts/                    what the agent is told: its role, and each surface's brief
├── catalogs/
│   ├── basic/                  vendored A2UI v0.9.1 basic catalog
│   └── a2ui-travel/            generated: basic + 12 travel components, and the examples
├── apps/
│   ├── server/                 ★ the Python server: the agent, the tools, the trip, MCP, voice
│   ├── web/                    React client: the three flows, the catalog and the wire inspector
│   ├── mcp-view/               the renderer as one self-contained HTML file, for MCP hosts
│   └── worker/                 the original TypeScript server — still deployed, being retired
├── packages/
│   ├── renderer/               React host for both catalogs, and the design system
│   ├── express/                the TypeScript Express port: lexer, parser, compiler, decompiler
│   └── trip/                   the TypeScript trip model — retiring with the Worker
├── tools/
│   ├── parity/                 the goldens, and the scripts that write them
│   ├── e2e/                    a whole browser turn against a scripted model
│   ├── eval/                   the flows graded against a real model, mechanically
│   └── screenshots/            the README's pictures and docs/catalog.md, reproducibly
├── plugins/                    the Claude plugin: skills and an MCP endpoint
├── scripts/                    setup, generation, parity, and repo extraction
├── docs/
│   ├── catalog.md              every component, pictured — generated, never written
│   ├── user-flows.md           the flows, and which rules are code rather than prompt
│   ├── demo-script.md          what to type, and what should come back
│   └── architecture.md         how a turn goes end to end, and why
└── skills/                     generated SKILL.md files, checked in
```

The Python server is the whole backend, and it is two packages: `brain/` — the
skills, the tools, the trip record, the surface passes — and `doors/`, which is
that brain reachable four ways. The TypeScript worker and `packages/trip` are
gone: the cutover is done, and the goldens in `tools/parity/` are what made
retiring them a non-event — they still pin the behaviour, now over one
implementation rather than two.

`packages/express` is what is left of the TypeScript, and it is no longer in the
agent's path: the server compiles Express with the official Python SDK. The two
pages that still use it — the protocol view and the component page — compile in
the browser to *show* the round trip, which is the one place a second
implementation earns its keep.

---

## Tests

```bash
npm test                              # TypeScript: the compiler and the renderer
npm run check                         # every generated artifact and every golden
python3 -m pytest apps/server/tests   # the Python server
python3 -m pytest tools/tests         # the build tooling
npm run e2e                           # a whole browser turn, against a scripted model
```

None of it needs an API key.

### The goldens, and why there are six

They were written when two servers implemented the same agent, and the
dangerous failure there is not a break — a break is visible — but *silent
disagreement*: both answer, both draw something, and only the details differ. So
every layer where that could happen got a golden file the TypeScript wrote and
the Python had to reproduce exactly.

There is one server now, and the goldens are why deleting the other one was a
non-event. They kept their value in the process: a golden over code is an alarm
for a change nobody meant to make, which is the same job on one implementation
as on two. Only the prompt golden is *meant* to move, because it is assembled
from markdown people edit on purpose — so that one is re-recorded deliberately
and CI fails if you forget.

| Golden | Pins |
| --- | --- |
| `travel.json` | what the fixtures generate — the same airlines, times and fares |
| `trip.json` | the trip model: what blocks what, and what to ask for next |
| `tools.json` | the tools' *manners* — how a refusal is worded, which stop of a route a call is about |
| `prompt.json` | the whole system prompt, byte for byte, across seven trips and three surfaces |
| `skeleton.json` | the compiled skeleton — which also proves the two Express compilers agree |
| `surface.json` | the four passes the server makes over a surface before it goes out |

The working rule, which has paid for itself repeatedly: **write the golden from
the incumbent before porting, then check the golden fails when you break the
port.** Doing it that way found nine divergences in the tool layer alone, a
32-bit arithmetic bug, a case where two colliding keys came out in a different
order in each language — and two bugs that turned out to be in the *original*, so
a faithful port was the thing that surfaced them.

### What the rest cover

- **Parity** — 20 Express programs compiled by both implementations, plus a
  compile → decompile → compile round trip for each.
- **Streaming** — sentinels split across chunks, partial trees rendering, syntax
  errors reported only once a block is finished. Twice: once in TypeScript, once
  in Python.
- **The agent loop** — against a scripted model, because everything that goes
  wrong in a turn is about *order* and none of it throws: that a surface paints
  before the turn ends, that the skeleton goes out before the tool runs and the
  fill after it, that a value the traveller set reaches the trip without the
  model being asked, and that parallel tool results come back in one message.
- **MCP** — driven as a protocol, not as functions: handshake, batches,
  notification semantics, error codes, the three flows, and that the shipped
  HTML view fetches nothing.
- **The host** — data binding, list templates, client-side checks, and that a
  re-sent component replaces rather than duplicates.
- **The skills** — that the model-facing fields leak no implementation detail,
  that the modular pair covers the monolith, and that no skill ships a script.
- **Every catalog function** — driven from `catalog.json` rather than from the
  code, so a function declared and not implemented fails. That is the gap
  `formatString` shipped through: it never implemented its own spec, nothing
  threw, and the tests agreed because they were written from the implementation.
- **Voice** — the `setup` frame the Live API would accept, and that a surface
  tool hands the model a summary rather than the flight list.
- **End to end** — a real browser: type a message, watch a surface appear
  mid-stream, click a flight, and assert the click reaches the model as the next
  turn with the surface's data model attached.

---

## Notes on the parts that are simulated

**The travel data is generated, and the app says so on screen.** There is no
booking system here, no payment, and no live carrier. What there is:

- **Real** — the destination guides, the neighbourhoods, the currencies, the
  best months to go. Those are researched facts in `data/destinations.json`.
- **Generated** — every fare, schedule, hotel and forecast. Deterministic, so
  the same query returns the same flights every time: a screenshot stays true, a
  test can assert on a price, and reloading does not give you a different trip.

Every answer carries its own **provenance** — a source, a plain-language label,
and a sentence explaining it — and `/api/meta` advertises it so the chrome can
say it once rather than every card carrying a badge.

An earlier version of this section claimed the fixtures could be swapped for a
real API and nothing above would change. That was an assertion rather than a
seam, and being an assertion it hid four ways to answer a question with
something untrue:

| asked | answered |
| --- | --- |
| flights under $1 | an empty list, under a heading that said flights |
| flights to Reykjavik | four flights to `REY`, an airport code taken from the first three letters |
| hotels in Reykjavik | four Madrid hotels in Lavapiés, priced in euros, captioned "4 stay(s) in MAD" |
| anything at all | nothing on screen said the numbers were invented |

All four are one bug: a function that could not say *"I don't know"* said
something else instead. So the seam is real now, in
`apps/server/src/travel_a2ui/brain/providers/`, and not-knowing is the only
alternative to knowing:

- A provider **cannot** return an empty success. The constructor refuses to
  build one, so "no results" is unrepresentable rather than merely discouraged.
- A filter that matches nothing is **widened, and the widening is named** — "the
  $1 cap" — because a cheaper flight with a stop is not the flight that was
  asked for.
- A destination the provider has never heard of is a **refusal with
  alternatives**, not an invented airport code.
- `AmadeusProvider` is the live implementation, and ships unconfigured. Set
  `AMADEUS_CLIENT_ID` and the same surfaces are drawn from real inventory, with
  the provenance on screen changing to say so.

---

## Credits and licence

Apache-2.0. See [NOTICE](NOTICE).

Built on [A2UI](https://a2ui.org) by Google. The Express compiler and the
signature generator are ports of the reference implementations in
[google/a2ui](https://github.com/google/a2ui) (Apache-2.0), kept honest by the
parity suites described above. The basic component catalog is vendored from that
repository's `specification/v0_9_1`.
