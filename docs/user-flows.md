# User flows, and the edge cases that shaped them

Written before the code it describes, and kept in step with it since. The
implementation notes at the end of each section say where a rule is *enforced*
rather than merely requested, because the difference matters: a rule in the
prompt is a request to a model, and a rule in the host is a guarantee.

---

## The one-sentence model

**The conversation is where you decide. The panel is where decisions live.**

Everything follows from that split:

| | Conversation (inline) | Panel (right) |
| --- | --- | --- |
| Contains | the question being asked right now | what has been settled |
| Interactive | yes, the newest card only | no — except "change this" |
| Lifetime | one card per turn, kept as a record | one surface, replaced as the trip moves |
| Written by | the agent, per turn | the agent, from the trip |

A control that edits something appears **only inline**. The panel never asks you
anything. This started as two places you could change the same value, and the
result was a conversation that could not tell you where an answer came from —
so the panel gave up its controls and kept the record.

---

## Flow 1 · Opening a trip

**Someone says what they want.** "SFO to NYC via Chicago for a wedding."

1. The agent records the route — all of it, in one call, including stops, why
   each exists, and where the party size differs.
2. It works out what is *missing* for the next step and asks for **all of it in
   one surface**: dates, departure airport, how many people — each in a control
   the answer cannot be wrong in. Airports are a `ChoicePicker` of the airports
   this deployment actually serves; dates are a `DateRangePicker`; the party is
   a `TravelerCounter`. Pre-filled with anything they already said.
3. One button. Editing sends nothing.
4. Pressing it sends one message. Everything above greys out.

**Edge cases**

| Case | What happens |
| --- | --- |
| No dates given | It asks. It does **not** price "a sample week in April" — the pricing tools refuse without dates and return what to ask for. |
| No departure airport | **Asked, never inferred.** A timezone covers a continent-slice — `America/New_York` offered JFK to someone in Atlanta, 1,211 km away, with a fare attached — so the guess is gone and the question is a row of airport pills. |
| A date asked for in a text box | Refused before it is drawn. `data/controls.json` says which control each decision may be asked in, the prompt teaches it and the host checks it, so the model rewrites the surface rather than the traveller mistyping "April 12ish". |
| "Roughly what does April cost?" | Answered, and labelled *indicative*, because they asked for a rough figure rather than their trip. |
| Dates in the past | Refused at save, with the reason. April 2026 asked for in September 2026 means April 2027. |
| Return before departure | Refused at save. |
| A place the catalog does not know | Says so and lists what it does know, rather than inventing a guide. |

## Flow 2 · Choosing something

**Tapping a card is a decision.** A flight, a hotel: one tap sends, because
picking *is* the answer and a confirm button would be ceremony.

**Editing is not deciding.** A slider, a date, a counter, a checkbox: those
change the surface and wait. Three choices on one card are one answer.

**Edge cases**

| Case | What happens |
| --- | --- |
| Several things to set at once | One surface, one button, all values sent together. |
| The agent forgets a button | The server adds one before the surface is sent, bound to everything the card edits. A card of sliders you cannot submit is a dead end. |
| The agent forgets to bind a field | The server binds it. Nothing the traveler set is dropped because the model named three paths out of four. |
| Tapping an old card | Impossible. Only the newest surface is interactive. |
| A multi-leg trip | One surface per leg, each labelled with its own route, dates and party size. Tapping a fare decides that leg only. |

## Flow 3 · Seeing what is settled

The panel is the trip's state: the route, the decisions, the plan and how far
through it you are. It shows every stop with what is unusual about it — a
different party size, why the stop exists, a stop that needs no room.

It is **read-only**, with one exception: every locked decision carries a way to
change it.

**Edge cases**

| Case | What happens |
| --- | --- |
| A value changes on an inline card | The panel updates immediately, with no model turn — the server sends `updateDataModel`. Trip facts are shared state, not something the agent re-renders. |
| The plan moves on | Same: the checklist is bound to `/plan`, which the server keeps current. The agent drew the shape once. |
| Nothing decided yet | The panel says what the agent is about to ask, rather than showing an empty form. |
| Something the trip does not need | Struck through and marked *not needed*. Never asked about again. |
| A stop still missing something | Flagged on that stop — `dates?`, `stay?` — not as a trip-wide gap. |

## Flow 4 · Changing your mind

The important one, and the reason the panel is read-only.

1. In the panel, press **Change** on a locked decision.
2. That decision is **released** — cleared from the trip, so nothing downstream
   still prices against it.
3. The agent re-opens it **inline**, pre-filled with what was there, alongside
   anything that depended on it.
4. You change it and commit, exactly like the first time.

Changing it in the panel directly would mean two places that edit the same
thing, and a conversation with no record of when it changed. Releasing it back
into the conversation keeps one editing surface and one history.

**Edge cases**

| Case | What happens |
| --- | --- |
| Changing something others depend on | The dependents are released too. A new date range releases the flight priced against it, and the agent says so. |
| Changing something that was ruled out | It comes back — "actually, we do need a hotel in Madrid" un-skips it. |
| Changing after the trip is finished | The plan reopens at that step. |
| Pressing Change twice | The second is a no-op; it is already released and open inline. |

## Flow 5 · Somewhere to stay

Three cities do not mean three hotels, so this is asked **per stop**: which of
these need a room, and which do not. A friend's spare room, a wedding block, a
red-eye out the same night — all reasons a stop needs nothing.

Answered once per stop and never asked again. Stays are then found only for the
stops that need one.

## Flow 6 · Planning the days

The first five flows settle *facts*. This one curates a *list*, and the
difference changes the interaction.

A decision — a flight, a date — is locked once made and changed by releasing it.
A day plan is never locked: it is a draft you push around. So the day cards are
the one place the panel is **editable in place**.

1. The agent draws a card per day, each with its activities in time order.
2. Every activity carries **remove**, and the day carries **add something else**.
3. Removing is immediate and local — the data model changes, no model turn, no
   waiting. `callFunction` recomputes the day's hours as it goes.
4. The turn commits when they press **looks good** or **more options**, which is
   what makes a dozen small edits one message instead of a dozen.

**Edge cases**

| Case | What happens |
| --- | --- |
| Removing everything from a day | The day stays, empty, offering to fill itself. An empty day is a real answer — a rest day — and deleting the card would lose the date. |
| Editing after "looks good" | Same as any decision: it reopens. The day plan is the one that is *expected* to be revisited. |
| Typing instead of pressing | Works. The buttons are the fast path, not the only path — a typed "drop the museum, it's too far" is the same turn. |
| A day with nothing worth doing | Says so and offers the next town over, rather than padding the day. |

## Flow 7 · Sharing what you planned

A finished trip is a thing you send to whoever is coming.

1. The last surface carries **share** beside the plan.
2. Sharing produces the trip as a readable page — the route, each hop, each
   stay, the days, and what it comes to — not a screenshot of the app.
3. Nothing is booked and the page says so. The provenance label travels with it:
   sample fares are labelled sample fares wherever they end up.

## Flow 8 · Correcting the thing on screen

"NYC and all nearby airports" after a surface has already asked for a departure
airport is **not** the next step. It is the same step, asked again, wider.

1. A message that changes what the *last card* asked about redraws that
   question — same controls, more options, pre-filled with what was there.
2. It does not advance the plan and it does not start searching.
3. The card that was superseded greys out like any answered card; the
   conversation keeps both, because "I changed my mind here" is history worth
   having.

This is a rule the model follows rather than one the host enforces, and that is
the honest description: the host cannot tell a correction from a new request
without understanding the sentence.

## Flow 9 · Finishing

When every hop has what it needs and everything else is settled or ruled out,
the agent stops asking. It shows the
whole trip on one surface and offers the two things actually left — adding more
to the days, or sharing the plan with whoever else is coming — and wishes them a
good trip.

**Edge case:** a trip that will never be "complete" — someone browsing, someone
who only wanted a fare. There is no sequence to force — the agent decides each
turn what is worth asking next from what is now known, and something ruled out
is something finished.

## Flow 10 · Inside Claude

The same three placements travel to an MCP host, because they are properties of
where an answer goes rather than of this codebase. What does not travel is the
runtime picker — inside Claude, Claude *is* the runtime — and the panel's
read-only rule, because the host owns its own layout.

The pricing rules do travel: the MCP tools refuse to price a trip nobody has
described, in the same words, and name the `$/trip/…` paths to bind.

---

## Where each rule actually lives

The honest version, since a rule in a prompt is a request and a rule in the host
is a guarantee.

| Rule | Enforced in | Why there |
| --- | --- | --- |
| Editors never send | the renderer | A model that adds an action to a slider should not be able to break the interaction model. |
| Only the newest surface is interactive | the host (`inert`) | The agent has no idea what else is on screen. |
| Trip values pre-fill every surface | **the server** (`createSurface.dataModel`) | Prompting a model to remember state it cannot see is how it forgets — and doing it in the browser is how only one client gets it right. |
| A panel stays current as the trip moves | **the server** (`updateDataModel`) | Same reason. It is a message every renderer already applies, so it costs a mobile client nothing. |
| Everything on a surface is sent together | **the server** (`bind_commit_context`) | Every path the editors write to is bound into the commit button before the surface leaves the server. |
| A card of editors is never a dead end | **the server** (`bindCommitContext`) | A surface with editors and no button gets one. This used to be a bar the React app drew, which meant the Flutter client shipped the dead end. |
| No prices without dates and a route | the tools | A model in a hurry prices a plausible week and calls it a sample. |
| A date range that ends before it starts | the tools | Silent corruption of everything downstream. |
| One surface, one button, ask for everything | the skill | A judgement call about layout, which is the model's job — and now one it cannot get *wrong* in a way that loses an answer. |
| Which control a decision may be asked in | **`data/controls.json`**, taught by the skill and checked by the host | One table read twice. A rule stated in a prompt and enforced by a separate hand-kept list is two rules, and they drift the first time somebody edits one. |
| A component the catalog does not define | the host, before compiling | The SDK drops an invented component silently, so a surface made only of them compiles to an empty box with no error anywhere. |
| A child nobody defined | the host, via the SDK validator | `Column([head, footer])` with no `footer` is valid Express and renders a hole. Compiling is not validating. |
| A flight for every hop, including home | **the trip model** | The model believed a one-leg trip was complete the moment the outbound was chosen, and moved on to hotels with the traveller still in New York. |
| What this deployment has data for | **the data**, and the prompt says so | The list of airports in the prompt was a promise `search_flights` refused to keep: it invented a fare from any three letters, so the typed agent priced a trip the voice agent had just refused. |
| Say what a price is priced against | the skill, from a value the tools supply | The wording is the model's; the facts are not. |
| Lead the trip; know when to stop | the skill, from the model's plan | Same split: the sequence is computed, the phrasing is not. |

Four of those moved from the browser to the server, and the reason is the same
in every case: a rule enforced in the web app is a rule only the web app obeys.
The same session opened in the Flutter renderer now gets pre-filled
controls, a live panel, and a surface it can always submit — with no
travel-specific client code, because there is none left to write.

What crosses the wire when you press something is A2UI's own action envelope:

```json
{ "action": { "name": "search_flights", "surfaceId": "inline-1",
              "sourceComponentId": "go", "timestamp": "…",
              "context": { "origin": "JFK", "startDate": "2027-04-12" } } }
```

It used to be a sentence this app composed and nothing parsed. What that press
*means* — that a tap on the read-only panel is a request to re-open a decision,
say — is now said once, on the server, because it is a fact about this agent and
not about the tap.

So: **not all of it is better skills.** The prompt carries taste — what to draw,
what to say, when to have an opinion. The parts that must not vary are code,
because the alternative is an app whose correctness depends on a model having a
good day.

And the skills are checked like anything else. `tools/eval/live.mjs` runs these
flows against the real model and grades what comes back mechanically — which
tools were called with what, which components a surface holds, whether an editor
carries an action, what the trip ended up containing. Nothing is judged by
another model, because a grader that is itself a language model makes the suite
exactly as trustworthy as the thing it grades.

It has already earned its keep. Three findings on the first two runs: a block
that would not compile because the model wrote `duration:` where the grammar
wants `duration=`; a compile error nobody was ever told about, least of all the
model that could fix it; and a panel drawing controls because "lead the trip"
and "the panel is read-only" contradicted each other on a panel turn. None of
those were visible from the code, and none would have been caught by a scripted
test — the scripted tests pass a model that behaves, and the question was
whether it does.
