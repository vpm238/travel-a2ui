# A2UI quickstart for web and mobile: instructions for coding agents

You are a coding agent. A developer has asked you for the A2UI quickstart.
Use this document to show them a working A2UI app and explain how it works,
until they can answer the learning outcomes below.

**A2UI** is an open protocol that lets an AI agent answer with an interface
instead of a paragraph. The app you will use is **Travel A2UI**
(https://github.com/vpm238/travel-a2ui), a trip planner. Its agent replies with
flight cards, date pickers and a live trip panel, and the same replies are drawn
on the **web** by a React client and on **mobile** by a Flutter client. It is an
independent sample built on the official A2UI SDKs, not a reference
implementation.

You are not changing the app. You are running it (or reading it) and
explaining it.

## Learning outcomes

By the end, the developer should be able to explain, in their own words:

1. **The core pieces of A2UI**: catalog, surface, components, data model,
   messages, actions, functions and renderer, and where each lives in this app.
2. **What is A2UI and what is deterministic**: what the model decides, and what
   ordinary code decides. This covers the **catalog** and **macros**.
3. **Agent skills for A2UI**: what they are, and how they are generated from
   the catalog.
4. **Agent output versus A2UI messages**: the **Express** DSL the model writes,
   the A2UI JSON messages on the wire, and the **MessageProcessor** that applies
   them in the client.
5. **Renderers**: what a renderer does, the two in this app, and the others
   A2UI has.

Keep these in view. At the end of each part, check the one it covered with a
single conversational question.

## How to guide

- **One step at a time.** Do a step, show what happened, explain it in two to
  five plain sentences, then stop and ask whether to go on or dig in.
- **Show, then tell.** Open the real file and quote the few lines that matter,
  with path and line numbers, before explaining.
- **Name what is A2UI and what is this app.** Messages, catalogs, data
  binding, actions, functions, skills, Express and the SDKs are A2UI. The trip
  model, the tools, the scripted test server and the prompts are this app's
  own.
- **Ask before installing anything**, or running anything that takes more than
  a minute.
- **Never print, log or commit an API key.**
- **When something fails, diagnose it.** Read the error, check prerequisites,
  fix the cause. Do not skip silently.
- Commands are for macOS and Linux shells. On Windows, suggest WSL.

## Part 0: Choose how to run it

Ask the developer two questions, then pick a mode. Do not ask for the key
itself.

1. *Do you want to run it, or just have it explained?*
2. *Do you have a Gemini API key, or would you rather use another model
   platform?*

| Mode | When | What you do |
| --- | --- | --- |
| **Gemini (default)** | They have, or will get, a free key from https://aistudio.google.com/apikey | Run the app with `GEMINI_API_KEY` set in their shell (Part 2). |
| **Mock** | No key, or they want zero cost | Run the app without a key, plus the **scripted server**: the real server with a script standing in for the model (Part 3). Everything in this guide works except open conversation. |
| **Another platform** (Claude, OpenAI, a local model) | They want to see A2UI on their own model | Start in Mock mode. In Part 7, show the one seam where the model is called and what an adapter must produce. Offer to write a local adapter. The skills, prompts and tools are plain text and JSON Schema, so they carry over unchanged. |
| **Explain only** | They cannot or do not want to run code | Clone (or read on GitHub) and explain from the files, the hosted demo at https://travel-a2ui-vy7stnte2a-uc.a.run.app (Flutter at `/flutter/`) and the screenshots at https://travel-a2ui-vy7stnte2a-uc.a.run.app/docs/quickstart/. Skip the commands; keep the explanations and checks. |

Prerequisites for running it: `git`, Node 20+, Python 3.11+. The Flutter SDK
(3.47+) is optional, needed only to build the mobile client locally.

## Part 1: Clone, set up, and the architecture

```bash
git clone https://github.com/vpm238/travel-a2ui
cd travel-a2ui
npm run setup        # 1–2 minutes: .venv, packages, generated files, web build, tests
```

While it runs, explain the architecture. This is a quickstart for **web and
mobile** from one backend:

```
 Flutter client (mobile)        React client (web)
 renderers/flutter/             renderers/react/ + apps/web/
            \                      /
             \   A2UI messages    /      the same messages to both
              \  over SSE        /
          Python agent server  (apps/server/src/travel_a2ui/)
          · brain/  decides: the agent loop, tools, the trip, macros
          · doors/  transport: HTTP + SSE, voice WebSocket
          · A2UI agent SDK: parses and validates what the model writes
                       |
                     Gemini (Interactions API; Live API for voice)
```

One server serves the API, the React app at `/` and the Flutter app at
`/flutter/`. Neither client knows anything about travel. Each only knows how to
draw the catalog's components.

## Part 2: Run it

```bash
source .venv/bin/activate
export GEMINI_API_KEY=...     # Gemini mode only. The developer types it; never echo it.
uvicorn travel_a2ui.doors.http:app --port 8080 --app-dir apps/server/src
```

Have them open http://127.0.0.1:8080. With or without a key:

- **The sample trip** they land on is a recorded real conversation, replayed
  through the same code as a live turn.
- **The Catalog tab** draws every component the agent may use, with no model
  involved.
- **The Wire tab** shows each surface as the model wrote it (Express) beside
  the A2UI JSON the client received.

In Gemini mode, suggest *"Six days in Madrid in April, two of us, around
$2,500 all in"* with the Wire tab open in a second window.

Mobile: Flutter is how this app reaches mobile. In this repository it is built
for the web and drawn in a phone layout (inside a phone frame on a wide
screen). The same Dart code can target iOS and Android, but those targets are
not set up here (`flutter create --platforms=ios,android .` would add them).
Open http://127.0.0.1:8080/flutter/ if they built it (`cd renderers/flutter &&
flutter build web --release --base-href=/flutter/`), or the hosted one at
https://travel-a2ui-vy7stnte2a-uc.a.run.app/flutter/.

## Part 3: Outcome 1, the core pieces of A2UI

Watch one turn on the wire. In a second terminal, start the scripted server
(the mock; it needs no key and is a test tool of this app):

```bash
source .venv/bin/activate
GEMINI_API_KEY=scripted python tools/e2e/scripted_server.py 8130
```

In a third, ask for flights and print only the A2UI messages:

```bash
curl -sN -X POST localhost:8130/api/chat \
  -H 'content-type: application/json' \
  -d '{"message":"flights to Madrid"}' \
| python3 -c 'import sys, json
for line in sys.stdin:
    if line.startswith("data: "):
        event = json.loads(line[6:])
        if event["type"] == "ui":
            for message in event["messages"]:
                kind = next(k for k in message if k != "version")
                print(kind, json.dumps(message[kind])[:110])'
```

The script plays one conversation; `curl -X POST localhost:8130/__test__/reset`
starts it again. Expect a `createSurface` for `inline-1`, then one
`updateDataModel` for `/flights`. Rerun without the filter if they want to see
whole messages: before the A2UI arrive a `tool` event (the search) and its
`tool_result`. Then open http://127.0.0.1:8130 in a browser, type anything and
press a flight. The press appears as "from the interface": that is an
**action** going back, as an A2UI v1.0 renderer-to-agent message. The request
also carries the renderer's capabilities and the data model of every surface
that asks for answers; `docs/transport.md` describes the whole exchange.

Now name the pieces, pointing at what they just saw:

| Piece | What it is | Here |
| --- | --- | --- |
| **Catalog** | The JSON Schema of every component and function the agent may use | `catalogs/a2ui-travel/catalog.json` |
| **Surface** | A region of UI with an id, created by `createSurface` | `inline-1` above; the trip panel is another |
| **Components** | A flat list of typed nodes with ids; `root` is drawn first | the `components` array |
| **Data model** | A JSON document per surface; components bind to it by path | `{"@path": "airline"}`, rows at `/flights` |
| **Messages** | `createSurface`, `updateComponents`, `updateDataModel`, `deleteSurface` | the stream above |
| **Actions** | What a press sends back, as a v1.0 action with bound values resolved | `select_flight` with the flight `id` |
| **Functions** | Pure functions the client evaluates against the data model | `formatCurrency`; the catalog's own `calcNights` |
| **Renderer** | Applies messages and draws components with native widgets | React and Flutter clients |

Point out that the components carry no flight data: `FlightOption` is a
template repeated for each row at `/flights`, and the rows arrive in one
`updateDataModel` from the host. The other events in the stream (`text`,
`tool`, `trip`) are this app's envelope, from
`apps/server/src/travel_a2ui/doors/interactions/turn.py`.

**Check:** *Where do the flight cards get their airline and price from?*

## Part 4: Outcome 2, what is A2UI and what is deterministic

This is the most important distinction in the tour. The model decides **what
to show**. Ordinary code decides **everything that must not vary**.

**The catalog is the boundary.** The model can only use what the catalog
defines, and every message is validated against it.

- `catalogs/a2ui-travel/catalog.json` extends the A2UI **basic catalog**
  (`Text`, `Row`, `Column`, `List`, `Button`, `TextField` and so on) with
  travel components: `FlightOption`, `HotelCard`, `DateRangePicker` and others.
- It is generated: `scripts/build_catalog.py` takes the basic catalog from the
  A2UI SDK and adds the travel components. Show where `FlightOption` is
  declared there.
- Three readers share the one document: the server
  (`apps/server/src/travel_a2ui/brain/catalog.py`), the React client
  (`renderers/react/src/catalog.ts`) and the Flutter client
  (`renderers/flutter/lib/catalog.dart`).

**The model composes every surface.** The server never draws a surface and
never rewrites one. Open `apps/server/src/travel_a2ui/brain/ui.py`: every
message the model's Express produces is applied to a mirror of what the
renderer holds (the SDK's `RendererState`) before it is sent. A block that
does not apply goes back to the model with the reason, once; the host does not
fix it up.

**Macros are templates the model calls.** Open
`apps/server/src/travel_a2ui/brain/macros.py`. A macro is a one-line component
the model writes: `Flights(...)`, `Stays(...)`, `Highlights()`, `Itinerary()`
or `Trip()`. The server expands it with the A2UI SDK's `MacroExpander`
(`EXPANDER` and `expand` near the end of the file) into catalog components
bound to data the host publishes (`/flights`, `/hotels`, `/trip`, `/panel`;
the table is in `prompts/data.md`). The host sends the data, and only for the
paths a surface binds (`apps/server/src/travel_a2ui/brain/data.py`).

- The model still decides *whether*, *when* and *where* to draw a list of
  flights, and what goes around it. The macro saves it from retyping four
  `FlightOption`s of data the tool just returned. That costs hundreds of output
  tokens, and it is where a model could disagree with what was actually found.
- The trip panel is the same: the model draws it once with `Trip()`, and the
  host keeps it current with `updateDataModel`, never by redrawing it.
- Macros are in the model's catalog (`with_macros`) and its skill, but **not**
  in `catalog.json`. Renderers never see a macro.
- Show it: compile one line and watch it become catalog components:

  ```bash
  printf '%s' '[{"surfaceId":"inline-1","source":"fares = Flights(\"Outbound · JFK → MAD\", \"/trip/selectedFlight\")\nroot = Column([fares])"}]' \
  | python tools/e2e/compile.py | python3 -m json.tool
  ```

Then walk the table, opening one or two files they are curious about:

| Decided by the model (A2UI) | Decided by code (deterministic) |
| --- | --- |
| Whether to draw, and which components | What components exist: the catalog |
| Layout, headings, wording | Macro expansion: `apps/server/src/travel_a2ui/brain/macros.py` |
| Which tool to call, with what arguments | Tool results: `apps/server/src/travel_a2ui/brain/tools/run.py`, fixture data in `data/` |
| What to ask next: `prompts/flow.md` | That a date is asked in a date picker: `apps/server/src/travel_a2ui/brain/controls.py` |
| | Recording a press onto the trip: `apps/server/src/travel_a2ui/brain/presses.py` |
| | Presses answered with no model at all: `apps/server/src/travel_a2ui/brain/host_actions.py` |
| What goes on every surface, the panel included | That every message applies to what the renderer holds: `apps/server/src/travel_a2ui/brain/ui.py` |
| | The data each surface binds, kept current: `apps/server/src/travel_a2ui/brain/data.py` |
| | In the client: rendering, data binding, functions such as `calcNights` |

The rule the app follows: *anything that must not vary belongs in code, not in
the prompt.* A rule in a prompt is a request to a model; a rule in code is a
guarantee.

**Check:** *Name one thing the model decides here, and one thing it cannot get
wrong because code decides it.*

## Part 5: Outcome 3, agent skills for A2UI

A **skill** is a markdown file that teaches a model to write A2UI for a
specific catalog. Open both:

- `skills/express-modular/a2ui-core/SKILL.md`: the **notation**. It covers how
  to write Express, the `<a2ui>` tags, and the rules that never vary between
  catalogs.
- `skills/express-modular/a2ui-travel/SKILL.md`: the **catalog**. Each
  component appears as a positional signature with every property's
  description, for example
  `FlightOption(airline, departTime, arriveTime, ...)`, plus the macros.

They are **generated, never hand-written.** The pipeline:

```
scripts/build_catalog.py  →  catalog.json ┐
brain/macros.py, catalogs/a2ui-travel/examples/*.json ┴→ A2uiRequestProcessor (brain/catalog.py)
                                                         ├→ SkillGenerator(processor.format) → skills/*/SKILL.md
                                                         ├→ processor.prompt_snippet → this agent's own prompt
                                                         └→ the parser that reads what the model writes
```

One processor configuration teaches other agents (the skills), teaches this
one (the prompt snippet), and holds it to the result (the parser), so the three
cannot disagree; `apps/server/tests/test_skills.py` checks it. `npm run
generate` runs all of it, and `npm run check` fails CI if a skill drifts. Contrast with `prompts/`: `flow.md` and `role.md` are
authored judgement (what to ask, when). Both reach the model in one system
prompt; only the skills are derived.

Prove it with one edit (then undo it with `git checkout .`):

1. In `scripts/build_catalog.py`, change the description of `FlightOption`'s
   `airline` property.
2. Run `npm run generate`, then `git diff --stat`.
3. One edit lands in three files: the script, `catalog.json` (what renderers
   read) and `skills/express-modular/a2ui-travel/SKILL.md` (what the model reads).

**Check:** *Why generate skills instead of writing them?*

## Part 6: Outcome 4, agent output versus A2UI messages

There are two representations of the same interface, and a piece of software
on each side.

- **Agent output: Express**, a compact DSL the model writes inside `<a2ui>`
  tags:

  ```text
  head = Text("### Flights to Madrid")
  row  = FlightOption($airline, $departTime, $arriveTime, $origin, $destination,
                      $price, Event("select_flight", {id: $id}))
  list = List(_template($/flights, row))
  root = Column([head, list])
  ```

- **On the server, the A2UI agent SDK's request processor reads it**
  (`A2uiRequestProcessor.open_stream`, set up in
  `apps/server/src/travel_a2ui/brain/catalog.py`): it parses the Express as it
  streams, turns it into A2UI messages and validates them against the catalog.
  Messages go out as the model writes, so the surface paints before the reply
  is finished.
- **A2UI messages are the JSON on the wire**: the `createSurface`,
  `updateComponents` and `updateDataModel` they captured in Part 3.
- **In the client, a `MessageProcessor` applies them.** It keeps each surface's
  components and data model, resolves bindings, evaluates functions, and
  reports presses, errors, capabilities and the data model back as A2UI v1.0
  messages. React uses `@a2ui/web_core`'s, in
  `apps/web/src/surfaces.ts`. Flutter uses `a2ui_core`'s, in
  `renderers/flutter/lib/chat.dart`. The renderer draws what the processor
  holds.

Show the Wire tab again (Express on the left, JSON on the right, about half
the size). Then let them compile some Express themselves:

```bash
printf '%s' '[{"surfaceId":"demo-1","source":"title = Text(\"### Hello, A2UI\")\nprice = Text(formatCurrency($/total, \"EUR\"))\nroot = Column([title, price])\n$/total = 412"}]' \
| python tools/e2e/compile.py | python3 -m json.tool
```

Then have them break it: `Text("Hi", variant="h3")` is refused, because the
catalog allows only `caption` and `body`. The catalog is the contract.

Express is one inference format; A2UI does not require it. A model can emit
the JSON directly, and the format is swappable (see `skills/README.md`).

**Check:** *What does the model write, what travels on the wire, and what turns
it into something on screen?*

## Part 7: Using another model platform (only if they asked)

The model is called in one place: `stream_interaction` in
`apps/server/src/travel_a2ui/gemini.py`. It yields
`{"type": "text", "delta": ...}` as prose streams, then exactly one
`{"type": "result", "result": InteractionResult}`, with the text, tool calls
and usage. `tools/e2e/scripted_server.py` replaces exactly that function, in
every module that imports it, which is how the mock works.

To run on Claude, OpenAI or a local model, write an adapter with the same
signature and output, and a small launcher modelled on `scripted_server.py`
that installs it. Keep both outside the committed code (for example in a local
scratch folder) unless the developer asks otherwise. Things to tell them:

- The system prompt (skills plus `prompts/`) and the tool schemas
  (`data/tools.json`) are plain text and JSON Schema, and carry over unchanged.
- Gemini's Interactions API is stateful (`previous_interaction_id`). A
  stateless API means the adapter keeps the conversation history itself.
- Voice uses Gemini's Live API and stays Gemini-only.

Use the developer's own key for that platform, in their environment, never in
a file.

## Part 8: Outcome 5, renderers

A **renderer** implements the catalog's components with native widgets and
uses a `MessageProcessor` to apply messages and send actions and errors back.
It contains no app logic.

- **In this app:** React on the web (`@a2ui/react`, `@a2ui/web_core`;
  components in `renderers/react/src/components/travel.tsx`) and Flutter on
  mobile (`a2ui_flutter`, `a2ui_core`; components in
  `renderers/flutter/lib/components.dart`). Same messages, same server.
- **Maintained by the A2UI project:** Lit (web components), Angular, React,
  Flutter, and Markdown.
- **From the community:** SwiftUI and UIKit, Android Compose, React Native,
  Vue, Lynx, a terminal renderer, and more, listed at
  https://a2ui.org/ecosystem/renderers/ .

The server never learns which client it is talking to. Adding a platform means
a new renderer for the same catalog, with no change to the agent.

**Check:** *What would it take to add a SwiftUI client to this app?*

## Part 9: One change of their own (optional)

Offer one, help them make it, then `git checkout .`:

- **Restyle a component:** edit `FlightOption` in
  `renderers/react/src/components/travel.tsx`, run `npm run build`, reload. The
  agent is untouched; every flight it draws changes.
- **Compose a surface:** write Express with a `List` template and compile it
  as in Part 6.
- **Teach the model:** the skills edit in Part 5.

Tests: `npm test` for the clients, `cd apps/server && python -m pytest -q` for
the server.

## Part 9b: What is new in A2UI 1.0 (if they ask, or know 0.9)

Point at what this app uses, with the file:

- **Renderer capabilities** (`a2uiRendererCapabilities`): sent on every request
  by `apps/web/src/surfaces.ts`; negotiated in
  `apps/server/src/travel_a2ui/brain/catalog.py` with the SDK's
  `resolve_catalogs`.
- **Data model metadata** (`a2uiRendererDataModel`, on surfaces created with
  `sendDataModel`): how a form's answers reach the agent
  (`apps/server/src/travel_a2ui/brain/inbound.py`, `Canvas.edits`).
- **Renderer-to-agent `action` and `error` messages**, each with a `version`,
  validated with the SDK's v1.0 models.
- **Functions**: renderer-side catalog functions (`formatCurrency`,
  `calcNights`); 1.0 also lets an agent call a renderer function
  (`callRendererFunction`), which this app does not use.

Say plainly that the SSE and WebSocket envelope is this app's own
(`docs/transport.md`); A2UI's standard transports are A2A (`a2ui-a2a`) and ADK
(`a2ui-adk`).

## Part 10: Wrap up

Recap the five outcomes in a short table: outcome, one-line answer, where they
saw it. Then point them on:

- **Build your own:** the README section "Build one of your own" says what to
  change to make this about something other than travel.
- **A2UI docs:** https://a2ui.org (concepts, the v1.0 specification and the
  renderers).
- **Partner and consultant demos:**
  https://travel-a2ui-vy7stnte2a-uc.a.run.app/docs/ecosystem/partners/ shows
  A2UI in other products, and how teams brought it into their own stack.

Finally, ask what they want to build, and offer to sketch the catalog it would
need.
