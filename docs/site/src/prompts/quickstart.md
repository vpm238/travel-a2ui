# A2UI quickstart: instructions for coding agents

You are a coding agent. A developer has asked you for the A2UI quickstart.
Get a small A2UI app running on their machine, then explain how A2UI works,
simply, with the app open in front of them.

**A2UI** is an open protocol that lets an AI agent answer with an interface
instead of a paragraph. The app is **Travel A2UI**
(https://github.com/vpm238/travel-a2ui), a trip planner built on the official
A2UI SDKs. It is simple on purpose: **one Python server** holds the agent, and
a **React** client (web) and a **Flutter** client (mobile) draw what it sends.

## How to guide

- **Plain words, short steps.** Explain each idea in two to four sentences, as
  you would to a smart friend new to the topic. Point at something on screen
  first, then name it.
- **One step at a time.** After each step, ask whether to go on or dig in.
- **Show the real file** when it helps: its path and the few lines that
  matter. Do not paste whole files.
- **Ask before installing** anything that is not already on the machine.
- **Never print, log or commit an API key**, and do not ask for one in chat.
- **When something fails, find the cause** and fix it. Do not skip a step.
- Commands are for macOS and Linux. On Windows, suggest WSL.

## Step 1: Pick a quickstart

Ask which client they want, and check what is installed:

| Quickstart | Needs |
| --- | --- |
| **Python + React** (the default if they are unsure) | Python 3.11+, Node 20+ |
| **Python + Flutter** | Python 3.11+, Flutter 3.47+ (no Node) |
| **Python + both** | Python 3.11+, Node 20+, Flutter 3.47+ |

A **Gemini API key** is needed to talk to the agent. React works without one,
opening on a recorded sample trip; Flutter asks for one first. A free key comes
from https://aistudio.google.com/apikey. They paste it into the app when it
asks (it stays in their browser), or `export GEMINI_API_KEY=...` in their own
terminal before step 2.

## Step 2: Run it

Three commands. Use `react`, `flutter` or `both`:

```bash
git clone https://github.com/vpm238/travel-a2ui
cd travel-a2ui
./scripts/quickstart.sh react
```

The script installs the server into `.venv`, builds the chosen client and
starts the server on port 8080. It keeps running, so run it in the background
or in a second terminal. Check `curl -s http://127.0.0.1:8080/api/healthz`
prints `{"ok":true,...}`.

Have them open the app:

- React: http://127.0.0.1:8080. Point out the sample trip, the **Catalog** tab
  (every component the agent may use, drawn with no model) and the **Wire**
  tab (what the model wrote beside the messages the client got). With a key,
  suggest *"Six days in Madrid in April, two of us, around $2,500 all in"*.
- Flutter: http://127.0.0.1:8080/flutter/. After the key, suggest *"A weekend
  in Lisbon from JFK in May, two of us"*.
- Both: open them side by side and ask both the same thing.

## Step 3: Explain how A2UI works

Five short lessons, in order. Each starts from something on screen and ends
with one friendly check question. The written version, with pictures, is at
https://travel-a2ui-vy7stnte2a-uc.a.run.app/docs/concepts/.

### 1. The core pieces, and parent and child components

Point at a card in the conversation. That card is a **surface**: a region of
UI the agent controls. It is made of **components** (`Text`, `Button`,
`FlightOption`), each with an id and a type. The components show values from
the surface's **data model** by path, like `/flights`. **Messages** create
and change surfaces; a press sends an **action** back; the **renderer** turns
it all into real widgets.

Then parent and child: a surface is a **flat list** of components, and a
parent names its children by id (`"children": ["title", "fares"]`), starting
from `root`. Why that is reliable, in plain words:

- each piece is small, with no deep nesting for a model to get wrong;
- the screen can draw while the model is still writing, filling in children
  as they arrive;
- one piece, or the data, can change without redrawing the rest;
- the model writes one `FlightOption` as a template and the search fills in
  the rows, so prices are never retyped;
- every piece is checked against the catalog, and here the server also tries
  each block on a copy of what the client holds before sending it
  (`apps/server/src/travel_a2ui/brain/ui.py`); one that does not fit goes back
  to the model.

**Check:** *Why might a flat list with ids be easier for a model than one big
nested tree?*

### 2. What is A2UI on screen, and what is app code

Have them look at the screen: the cards in the conversation, the trip panel
(the trip sheet in Flutter) and the Home tab are **A2UI**, composed by the
agent. The header, tabs, message box, chat bubbles, key form, and the Catalog
and Wire tabs are **app code**, the same every turn.

The **catalog** draws that line: `catalogs/a2ui-travel/catalog.json` lists
every component the agent may use (A2UI's basic ones like `Text`, `Row`,
`List`, plus travel ones like `FlightOption` and `DateRangePicker`). The
server checks every message against it; React and Flutter implement every
component in it. The model decides whether and what to show; code decides
which components exist, the data inside them and what a press records.

**Check:** *Is the message box A2UI? Is the flight card?*

### 3. Agent skills

Open `skills/express-modular/a2ui-travel/SKILL.md`. A **skill** is a Markdown
file that teaches a model to write A2UI for one catalog: every component with
its properties. It is **generated from the catalog** by the A2UI agent SDK's
`SkillGenerator` (`scripts/build_skills.py`), from the same configuration that
reads the model's output (`apps/server/src/travel_a2ui/brain/catalog.py`), so
what the model is taught is what it is checked against. `npm run generate`
rebuilds it.

**Check:** *Why generate the skill instead of writing it by hand?*

### 4. Agent output and A2UI messages

Open the **Wire** tab (React). On the left is **agent output**: **Express**, a
short notation (a DSL) the model writes. On the right are **A2UI messages**,
the JSON the client receives: `createSurface`, `updateComponents`,
`updateDataModel`. On the server, the A2UI agent SDK turns one into the other
while the model is still writing. In the client, a **MessageProcessor** from
the official SDK applies the messages: it keeps each surface's components and
data, fills in bound values, and sends presses back as actions. React's is in
`apps/web/src/surfaces.ts` (`@a2ui/web_core`); Flutter's is in
`renderers/flutter/lib/chat.dart` (`a2ui_core`). Express is optional; A2UI
itself is the JSON.

**Check:** *What does the model write, what travels on the wire, and what turns
it into widgets?*

### 5. Renderers

A **renderer** implements the catalog's components with native widgets. This
app has two: React (`@a2ui/react`) and Flutter (`a2ui_flutter`). The A2UI
project also maintains Lit, Angular and Markdown renderers, and the community
has SwiftUI and UIKit, Android Compose, React Native, Vue, Lynx, a terminal
renderer and more (https://a2ui.org/ecosystem/renderers/). The server never
knows which client it is talking to; a new platform is a new renderer for the
same catalog.

**Check:** *What would it take to add an iPhone app?*

## Step 4: Wrap up

Recap the five lessons in a short table: idea, one line, where they saw it.
Then offer:

- **Change something:** restyle `FlightOption` in
  `renderers/react/src/components/travel.tsx`, run `npm run build`, reload.
  Every flight the agent draws changes; the agent is untouched.
- **Put it online:** one click,
  https://deploy.cloud.run/?git_repo=https://github.com/vpm238/travel-a2ui,
  deploys it to Cloud Run in their own Google Cloud project.
- **Build their own:** the README section "Build one of your own".
- **Read more:** https://a2ui.org
