# User flows, and how to demo them

Seven flows. Each one has a job, a script you can type verbatim, and what you
should see if it is working — so a reviewer can check it rather than take a
screenshot's word for it.

Flows 1–5 need the web app and an Anthropic key. Flow 6 needs nothing at all.
Flow 7 runs inside Claude.

```bash
npm run setup && npm run dev:worker
open http://127.0.0.1:8787/#key=sk-ant-...
```

Model **Opus 5**, skill **Express · one skill**, effort **Medium** unless a flow
says otherwise. Roughly 4–8 seconds per turn.

**Reloading starts a new conversation.** The transcript and the trip are gone;
your key is not. That is the fastest way to get back to a clean slate between
flows, and the ⟲ button in the header does the same without a reload.

---

## How the interface behaves

Worth knowing before you judge any flow, because it is deliberate:

- **Editing a control sends nothing.** Sliders, date pickers, counters, text
  fields and checkboxes change the surface and wait. A bar appears saying how
  many values are unsent.
- **Committing sends everything at once** — the agent's button, or the host's
  Send in that bar when the agent forgot one. It appears in the conversation as
  a message, tagged *from the interface*.
- **Tapping a card is a decision** and sends immediately, because picking a
  flight *is* the answer.
- **Answered surfaces go grey** and stop responding once you send. They stay as
  the record of what was chosen.
- **What you set on one card is filled in on the next.** Trip facts are shared;
  the sidebar updates the moment you change a route, without a model turn.
- **The agent leads.** There is a plan — route, dates, party, flight, stay,
  budget, days — shown as a checklist in the sidebar. Every turn moves it on or
  asks exactly what it takes to. When it is finished it says so and stops.

## Flow 1 · Inline — choosing, in the conversation

**The job.** The user is picking between options. Prose makes them hold five
flights in their head; an interface lets them look.

**Type:**

> I want to fly to Madrid in April with my partner. Show me options.

**Expect it to ask before it prices.** It does not know your dates or where you
are flying from, and it must not invent them. So the first card is a short form:
a departure airport pre-filled from your browser's timezone (a *suggestion* —
change it), a date range, a traveller count, and one **Search flights** button.

Set all three. Nothing sends while you do; a bar says *3 unsent changes*. Press
the button once and you get one message.

**Then expect the flights**, with a heading that says what they are priced
against — `LHR → Madrid · 12–19 Apr · 3 travellers`, not just "Flights to
Madrid" — and the form above them now greyed out and unclickable.

If you want a rough figure without committing to dates, say so:

> Roughly what does Madrid cost in April?

It will answer, and label the answer indicative.

**Then click a flight card.** That is a decision, so it sends immediately.
Watch for three things:

- A new user turn appears reading `[interface] select_flight (id: "IB6250",
  price: "$412")`. The click *is* the next turn — that is the whole round trip.
- The **Refine** sidebar fills in with real controls.
- **Decided so far** in the sidebar gains the flight.

The first card stays live and clickable. Scroll back and pick a different
flight; it works, because inline surfaces are per-turn and permanent.

## Flow 2 · The panel, and changing your mind

**The job.** The panel is the record of what is settled — read-only on purpose.
Deciding happens in the conversation, so there is one place to edit a value and
one history of when it changed.

**Look at the panel** after picking a flight: the route stop by stop, the flight
and its fare, the dates, and a checklist of the plan with the next step
highlighted. No sliders, no date pickers.

**Then press Change** on the flight.

**Expect:** it disappears from the panel, and a flight picker comes back *in the
conversation*, pre-filled — the agent will say what else that undid, because
releasing the flight also releases the fare it contributed to the total.

Now change something with dependents:

> Actually let's go a week later.

The dates release the flight priced against them, and the agent says so rather
than leaving a stale choice on screen looking settled.

## Flow 3 · Home — where the trip stands today

**The job.** Read first, not in reply to anything. A generated dashboard rather
than a fixed one.

**Click the Home tab.** Expect stat tiles (days out, travellers, estimate), a
budget meter, a weather strip, and a map of what is planned.

**Then, in Chat, change the layout by asking:**

> On my home screen, lead with the packing list and show the budget as a meter.

Go back to Home. The layout changed. That is the claim worth checking — a fixed
dashboard cannot do this, and nothing in the app was edited.

## Flow 4 · Composed on the fly — the general case

**The job.** Proving the six named surfaces are shortcuts, not the product.

**Type:**

> Before we book: show me what this costs, how much of my $2,600 budget it uses,
> a checkbox for the Schengen visa, and how it splits between the two of us.

**Expect** one surface containing a `PriceSummary`, a `ProgressMeter`, a
`CheckBox` bound to the data model, and an `ExpenseSplit` with per-person
shares. No tool in this codebase composes that. The model read the catalog and
wrote it.

Open the **Wire** tab afterwards and press *Show the A2UI Express*: you get the
source back, decompiled from the JSON, with the byte difference between the two.
Typically 60–70% smaller, which is why the model writes Express and not JSON.

## Flow 5 · A trip that does not fit the usual shape

**The job.** Proving the plan bends. Most demos assume one city, a flight and a
hotel; most trips are not that.

**Type:**

> SFO to NYC with 1 stop in Chicago for 2 nights to attend a wedding and then
> come back to SFO from NYC, but coming back it's 2 tickets because I'm
> travelling back with my friend.

**Expect** the whole route recorded in one go — three legs in the sidebar's plan
(Chicago → New York → San Francisco), the return marked `2×`, the wedding kept
as the reason for the stop — and then a single question about the dates. Not a
stop-at-a-time interrogation, and not a return priced for one person.

Then a simpler variant:

> Lisbon then Madrid, two weeks in April. We're staying with my sister in
> Lisbon.

**Expect** it to record Madrid as a second leg rather than losing it, note that
Lisbon needs no hotel, and ask only for what is missing — dates, airport, party
size — in one surface. Watch the checklist in the sidebar: the stay step should
narrow to Madrid rather than being asked twice.

Then rule something out:

> We're driving, no flights.

The flight step should go struck-through and *not needed*, and the agent should
move to the next step rather than asking about flights again.

## Flow 6 · No key, no model — the catalog and the MCP console

**The job.** Seeing A2UI render with nothing in the path. Good for a reviewer
who has no key, and the fastest way to prove the renderer is real.

**Click the MCP tab**, pick a tool, press run. A surface appears, composed
server-side from the catalog, with the JSON-RPC request and response beside it.
Nothing here calls a model.

**Click the Catalog tab.** Every component the agent can draw, with the exact
positional signature the model is given. Anything with a schema but no React
renderer is flagged in red — the gap is visible rather than discovered later.

Or open the standalone gallery, which needs no server at all:

```bash
npm run build -w @travel-a2ui/gallery
open apps/gallery/dist/gallery.html
```

Every surface there was compiled at build time from the catalog's own examples
by the real compiler, and every interaction is logged as the agent would receive
it.

## Flow 7 · The same three flows, inside Claude

**The job.** The interface layer travelling to a host that is not ours.

Install per [install-in-claude.md](install-in-claude.md), then:

> Use the travel tools to show me flights to Madrid.

You should get flight cards, not a bulleted list.

> Show me flights to Lisbon in the sidebar.

Same tool, `surface: "sidebar"` — three flights instead of four, and the panel
replaces itself rather than stacking.

> Read the A2UI component reference and compose me a pre-flight checklist: what
> the trip costs, how much of my $2,600 budget it uses, a visa checkbox, and how
> it splits between two people.

Claude calls `get_a2ui_component_reference`, writes A2UI Express, and sends it
to `render_a2ui_express`. This is flow 4, in someone else's app, with the same
components.

---

## The automated versions

Everything above has a scripted equivalent that needs no key and costs nothing.

```bash
npm run dev:worker      # in another terminal

node tools/e2e/chat.mjs   # flow 1, 14 assertions
node tools/e2e/mcp.mjs    # flows 4 + 6, 24 assertions
npm run e2e               # both
```

`chat.mjs` intercepts `/api/chat` and replays a canned turn through the *real*
stream splitter and compiler, so what reaches the browser is exactly the event
sequence a live turn produces — including the partial `ui` events from a
constructor split mid-stream. It then clicks a flight and asserts the click
became the next turn.

`mcp.mjs` speaks real JSON-RPC to a running server, takes the HTML out of a tool
result, and renders it inside a `sandbox="allow-scripts"` iframe — the strictest
thing a host does. It asserts the cards draw, the stylesheet crossed the origin,
the surface reported its height, clicking posted the intent a host forwards to
its model, and that a layout composed from the component reference draws every
kind it asked for.

To point either at a deployment instead of localhost:

```bash
BASE_URL=https://travel-a2ui.<subdomain>.workers.dev node tools/e2e/mcp.mjs
```

And to regenerate the README's screenshots from the same runs:

```bash
npm run screenshots
```

---

## Testing a live turn from the command line

No browser, one curl, real model:

```bash
curl -sN http://127.0.0.1:8787/api/chat \
  -H 'content-type: application/json' \
  -H "x-anthropic-key: $ANTHROPIC_API_KEY" \
  -d '{"sessionId":"demo","message":"Show me flights to Madrid for two in April.",
       "surface":"inline","surfaceId":"inline-1","model":"claude-opus-5"}'
```

You will see the SSE event stream directly: `start`, interleaved `text` and
`ui`, `tool` / `tool_result` pairs, `trip`, `usage`, `done`. The `ui` events
arrive partial and then `done: true`, which is progressive rendering as it looks
on the wire.

Against the managed-agent backend, the same request on port 8000 returns the
same event shape from a different runtime — that equivalence is the point, and
it is the fastest way to check it.
