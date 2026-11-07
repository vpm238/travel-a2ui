# A2UI quickstart: instructions for coding agents

You are a coding agent. A developer has asked you for the A2UI quickstart.
Set up a small A2UI app on their machine, one piece at a time, and explain
each piece in plain words as it starts working.

**A2UI** is an open protocol that lets an AI agent answer with an interface
instead of a paragraph. The app is **Travel A2UI**
(https://github.com/vpm238/travel-a2ui), a trip planner, and it is simple on
purpose:

- **one Python server** that holds the agent, and
- **two clients** that draw what the agent sends: **React** on the web and
  **Flutter** on mobile.

Both clients get the same A2UI messages from the same server. Neither knows
anything about travel. It is an independent sample built on the official A2UI
SDKs, not a reference implementation.

## How to guide

- **One step at a time.** Run the step, show what happened, explain it in two
  to four plain sentences, then ask whether to go on.
- **Show the real file** when you explain something: path and the few lines
  that matter.
- **Ask before installing** anything that is not already on the machine.
- **Never print, log or commit an API key.** Do not ask for one in chat.
- **When something fails, find the cause** and fix it. Do not skip a step
  silently.
- Commands are for macOS and Linux. On Windows, suggest WSL.

## Before you start

Check what is installed: `git`, **Python 3.11+**, **Node 20+**, and for step 3
**Flutter 3.47+** (`flutter --version`). Flutter is only needed for the mobile
client; everything else works without it.

A **Gemini API key** is optional for the React client: without one it opens
on a recorded sample trip, and its Catalog and Wire tabs work. The Flutter
client asks for a key before it starts. They can get a free key at
https://aistudio.google.com/apikey and paste it into the app when it asks; it
stays in their browser. Or they can `export GEMINI_API_KEY=...` in the
server's terminal before starting it, and neither client asks.

## Step 1: the Python server

```bash
git clone https://github.com/vpm238/travel-a2ui
cd travel-a2ui
python3 -m venv .venv
source .venv/bin/activate
pip install -e apps/server
uvicorn travel_a2ui.doors.http:app --port 8080 --app-dir apps/server/src
```

Keep the server running (a second terminal, or in the background) and check
it: `curl -s http://127.0.0.1:8080/api/healthz` prints `{"ok":true,...}`.
Opening http://127.0.0.1:8080 now says the React client is not built yet; that
is step 2.

**Explain:** the server is the agent. It sends the conversation to Gemini, and
the model answers with UI written against a **catalog**: the list of
components it may use (`catalogs/a2ui-travel/catalog.json`), such as
`FlightOption`, `DateRangePicker` and the basics like `Text` and `Column`. The
A2UI agent SDK checks every message against that catalog before it leaves the
server (`apps/server/src/travel_a2ui/brain/catalog.py`).

## Step 2: the React client (web)

In a new terminal, from the repository root:

```bash
npm install
npm run build
```

Reload http://127.0.0.1:8080. The server serves the build; no restart needed.

Show them around:

- **The sample trip** is a recorded real conversation, replayed through the
  same code as a live turn.
- **The Catalog tab** draws every component the agent may use, with no model
  involved.
- **The Wire tab** shows each surface twice: what the model wrote, and the
  A2UI JSON the client received.
- With a key, suggest *"Six days in Madrid in April, two of us, around $2,500
  all in"* and watch the cards arrive.

**Explain:** the model writes a compact notation called **Express**, and the
server turns it into **A2UI messages**: `createSurface` (a region of UI with
its components), `updateDataModel` (the data those components show) and so
on. For example, a flight list:

```text
head = Text("### Flights to Madrid")
row  = FlightOption($airline, $departTime, $arriveTime, $origin, $destination,
                    $price, Event("select_flight", {id: $id}))
list = List(_template($/flights, row))
root = Column([head, list])
```

`FlightOption` is a template repeated for each row at `/flights`, and the
server fills `/flights` with the search results, so the model never retypes
them. In the browser, the React **renderer** (`@a2ui/react` and
`@a2ui/web_core`, wired up in `apps/web/src/surfaces.ts`) applies the messages
and draws each component; the travel components are in
`renderers/react/src/components/travel.tsx`. A press goes back to the agent as
an A2UI **action**.

For hot reload while editing the client, run `npm run dev:web` instead and
open http://localhost:5173 (it uses the same server on port 8080).

## Step 3: the Flutter client (mobile)

```bash
cd renderers/flutter
flutter pub get
flutter build web --base-href=/flutter/
```

Open http://127.0.0.1:8080/flutter/. The server serves this build too. It asks
for a Gemini key first (unless the server has one); then suggest *"A weekend in
Lisbon from JFK in May, two of us"*.

If Flutter is not installed and they would rather not install it, show the
hosted one: https://travel-a2ui-vy7stnte2a-uc.a.run.app/flutter/.

**Explain:** this is the same agent, the same server and the same messages,
drawn by a second renderer (`a2ui_flutter` and `a2ui_core`; the travel
components are in `renderers/flutter/lib/components.dart`). Nothing on the
server changed. That is the point of A2UI: the agent describes an interface,
and each platform draws it with its own widgets. Here Flutter is built for the
web and drawn in a phone layout; the same Dart code can target iOS and
Android, which this repository does not set up.

## Step 4: deploy it to Cloud Run (optional)

Only if they want it online, in their own Google Cloud project (billing
enabled). The simplest way is one click, which needs nothing installed:

https://deploy.cloud.run/?git_repo=https://github.com/vpm238/travel-a2ui

It opens Cloud Shell, builds the app (about ten minutes the first time) and
deploys it to one URL that serves the server and both clients. No key is
stored on the service; each visitor pastes their own. If they have gcloud
signed in locally, `docs/deploying.md` has the one-command version.

## Wrap up

Recap in a short table, pointing at where they saw each:

| Idea | One line | Where |
| --- | --- | --- |
| **Catalog** | The components the agent may use | `catalogs/a2ui-travel/catalog.json`, the Catalog tab |
| **Messages** | The JSON the server streams: surfaces, components, data | the Wire tab |
| **Data binding** | Components show data by path, filled by the server | `/flights` in step 2 |
| **Renderer** | Draws the messages with native widgets | React in step 2, Flutter in step 3 |
| **Action** | A press, sent back to the agent | pressing a flight |

If they want more:

- **Change something:** restyle `FlightOption` in
  `renderers/react/src/components/travel.tsx`, run `npm run build`, reload.
  Every flight the agent draws changes; the agent is untouched.
- **How the model is taught:** `skills/` holds the A2UI instructions the model
  reads. They are generated from the catalog (`npm run generate`), never
  written by hand.
- **Another model platform:** the model is called in one function,
  `stream_interaction` in `apps/server/src/travel_a2ui/gemini.py`.
- **Build your own:** the README section "Build one of your own".
- **A2UI documentation:** https://a2ui.org
