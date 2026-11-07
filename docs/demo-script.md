# User flows, and how to demo them

Six flows. Each one has a job, a script you can type verbatim, and what you
should see if it is working — so a reviewer can check it rather than take a
screenshot's word for it.

Flows 1–5 need the web app and a Gemini key. Flow 6 needs nothing at all.

```bash
npm run setup                     # installs, regenerates, builds, tests; creates .venv
source .venv/bin/activate
uvicorn travel_a2ui.doors.http:app --port 8080 --app-dir apps/server/src
open "http://127.0.0.1:8080/#key=<your Gemini key>"
```

Default model and effort unless a flow says otherwise. Roughly 4–8 seconds per
turn; the interface itself appears well before that, which is the number that
decides how it feels — open the timing disclosure under any reply to see both.

**Reloading starts a new conversation.** The transcript and the trip are gone;
your key is not. That is the fastest way to get back to a clean slate between
flows, and the *Start over* button in the header does the same without a reload.

---

## How the interface behaves

Worth knowing before you judge any flow, because it is deliberate:

- **Every surface is composed by the agent.** The server never draws one and
  never rewrites one; it fills in the data a surface binds.
- **Editing a control sends nothing.** Sliders, date pickers, counters, text
  fields and checkboxes change the surface and wait.
- **Pressing the card's button sends everything at once** — an A2UI action,
  with the card's data model beside it. It appears in the conversation as a
  line in plain words: the button's label and the values it carried.
- **Tapping a card is a decision** and sends immediately, because picking a
  flight *is* the answer.
- **Answered surfaces go grey** and stop responding once you send. They stay as
  the record of what was chosen.
- **What you set on one card is filled in on the next.** Trip facts are shared;
  the panel updates the moment you change a route, without a model turn.
- **The panel is drawn once.** After the first turn that settles a destination
  the agent draws it, and from then on it moves by data alone.
- **The agent leads.** Every turn moves the trip on or asks exactly what it
  takes to. When everything is settled it says so and stops.

## Flow 1 · Inline — choosing, in the conversation

**The job.** The user is picking between options. Prose makes them hold five
flights in their head; an interface lets them look.

**Type:**

> I want to fly to Madrid in April with my partner. Show me options.

**Expect it to ask before it prices.** It does not know your dates or where you
are flying from, and it must not invent them. So the first card is a short form:
an airport picker for where you fly from (the airports this deployment serves,
with nothing guessed), a date range, a traveller count already set to two, and
one **Search flights** button.

Set them. Nothing sends while you do — editing is not deciding. Press the
button once and you get one turn carrying every value, because the card was
created to send its data model with the press.

**Then expect the flights**, with a heading that says what they are priced
against — `LHR → Madrid · 12–19 Apr · 2 travellers`, not just "Flights to
Madrid" — and the form above them now greyed out and unclickable. Watch the
flight card: it usually appears before the fares do, empty, and fills in when
the search returns.

If you want a rough figure without committing to dates, say so:

> Roughly what does Madrid cost in April?

It will answer, and label the answer indicative.

**Then click a flight card.** That is a decision, so it sends immediately.
Watch for three things:

- A new line in your side of the conversation, naming the fare you picked. The
  click *is* the next turn — that is the whole round trip.
- The panel appears beside the conversation (on a phone, as a bar above it),
  drawn by the agent.
- The flight is on its hop in the panel.

The flight card is now grey: it is the record of that answer. Changing it is
the next flow.

## Flow 2 · The panel, and changing your mind

**The job.** The panel is the record of what is settled — read-only on purpose.
Deciding happens in the conversation, so there is one place to edit a value and
one history of when it changed.

**Look at the panel** after picking a flight: the route hop by hop, with dates,
party size, the flight and its fare. No sliders, no date pickers.

**Then press Change** on the flight.

**Expect:** it disappears from the panel, and a flight picker comes back *in the
conversation*, pre-filled — the agent will say what else that undid, because
releasing the flight also releases the fare it contributed to the total.

Now change something with dependents:

> Actually let's go a week later.

The dates release the flight priced against them, and the agent says so rather
than leaving a stale choice on screen looking settled. The panel follows without
being drawn again.

## Flow 3 · Home — where the trip stands today

**The job.** Read first, not in reply to anything. A generated dashboard rather
than a fixed one.

**Click the Home tab, then Build home page.** Expect something like stat tiles
(days out, travellers, estimate), a budget meter, a weather strip and a map —
the agent chooses.

**Then, in Chat, change the layout by asking:**

> On my home screen, lead with the packing list and show the budget as a meter.

Go back to Home. The layout changed. That is the claim worth checking — a fixed
dashboard cannot do this, and nothing in the app was edited.

## Flow 4 · Composed on the fly — the general case

**The job.** Proving the macros are shortcuts, not the product.

**Type:**

> Before we book: show me what this costs, how much of my $2,600 budget it uses,
> a checkbox for the Schengen visa, and how it splits between the two of us.

**Expect** one surface containing a `PriceSummary`, a `ProgressMeter`, a
`CheckBox` bound to the data model, and an `ExpenseSplit` with per-person
shares. No tool in this codebase composes that. The model read the catalog and
wrote it.

Open the **Wire** tab afterwards: each surface on screen, as the JSON the
renderer holds and as the A2UI Express that produces it, decompiled by the A2UI
SDK on the server, with the byte difference between the two. Typically 60–70%
smaller, which is why the model writes Express and not JSON.

## Flow 5 · A trip that does not fit the usual shape

**The job.** Proving the plan bends. Most demos assume one city, a flight and a
hotel; most trips are not that.

**Type:**

> SFO to NYC with 1 stop in Chicago for 2 nights to attend a wedding and then
> come back to SFO from NYC, but coming back it's 2 tickets because I'm
> travelling back with my friend.

**Expect** the whole route recorded in one go — three hops in the panel
(Chicago → New York → San Francisco), the return marked for two, the wedding kept
as the reason for the stop — and then a single question about the dates, with a
traveller counter per hop. Not a stop-at-a-time interrogation, and not a return
priced for one person.

Then a simpler variant:

> Lisbon then Madrid, two weeks in April. We're staying with my sister in
> Lisbon.

**Expect** it to record Madrid as a second hop rather than losing it, note that
Lisbon needs no hotel, and ask only for what is missing — dates, airport, party
size — in one surface. Somewhere to stay should narrow to Madrid rather than
being asked twice.

Then rule something out:

> We're driving, no flights.

Flights should be marked *not needed*, and the agent should move on rather than
asking about flights again.

## Flow 6 · No key, no model — the catalog

**The job.** Seeing A2UI render with nothing in the path. Good for a reviewer
who has no key, and the fastest way to prove the renderer is real.

**Click the Catalog tab.** Every component the agent can draw, with the exact
positional signature the model is given. A component with a schema and no
view cannot ship: the client refuses the catalog at startup, by name.

Or open `/catalog/FlightOption` (any component name works): one component on
its own, drawn by `@a2ui/react` from messages the A2UI Python SDK read and
validated at build time.

The recorded sample trip on the Chat tab also plays with no key: a real
conversation with the agent, replayed through the same handler as a live turn.

## The automated versions

Everything above has a scripted equivalent that needs no key and costs nothing:
the real server, with a scripted model in place of Gemini.

```bash
GEMINI_API_KEY=scripted python tools/e2e/scripted_server.py 8130   # in another terminal

export BASE_URL=http://127.0.0.1:8130/
node tools/e2e/chat.mjs   # flow 1
npm run e2e               # all of the browser suites
```

`chat.mjs` stages its turns with Express read through the server's own pipeline
(`tools/e2e/compile.py`: the SDK processor, the macros and the renderer mirror),
so what reaches the browser is exactly the event sequence a live turn produces —
including a partial surface from a block cut off mid-stream. It then clicks a
flight and asserts the click became the next turn, as an A2UI v1.0 action.

To point one at a deployment instead of localhost:

```bash
BASE_URL=https://travel-a2ui-vy7stnte2a-uc.a.run.app node tools/e2e/chat.mjs
```

And to regenerate the README's screenshots from the same runs:

```bash
npm run screenshots
```

---

## Testing a live turn from the command line

No browser, one curl, real model:

```bash
curl -sN http://127.0.0.1:8080/api/chat \
  -H 'content-type: application/json' \
  -H "x-goog-api-key: $GEMINI_API_KEY" \
  -d '{"sessionId":"demo","message":"Show me flights to Madrid for two in April.",
       "surface":"inline","client":{"today":"2027-03-01","locale":"en-US"}}'
```

You will see the SSE event stream directly: `session`, `start`, interleaved
`text` and `ui`, `tool` / `tool_result` pairs, `trip`, `usage`, `resume`,
`done`. The `ui` events carry A2UI v1.0 messages, arriving partial and then
`done: true`, which is progressive rendering as it looks on the wire. Every
event is described in [transport.md](transport.md).
