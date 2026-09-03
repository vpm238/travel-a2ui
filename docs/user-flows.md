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
   one surface**: dates, departure airport, how many people. Pre-filled with the
   best suggestion it has — the departure airport from the browser's timezone,
   the dates from anything they said.
3. One button. Editing sends nothing.
4. Pressing it sends one message. Everything above greys out.

**Edge cases**

| Case | What happens |
| --- | --- |
| No dates given | It asks. It does **not** price "a sample week in April" — the pricing tools refuse without dates and return what to ask for. |
| No departure airport | Suggested from the timezone, shown pre-filled, never assumed. If the timezone is unknown, it asks outright. |
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
| The agent forgets a button | The host draws one — a bar saying how many values are unsent, with Send. A card of sliders you cannot submit is a dead end. |
| Editing, then editing back | The bar disappears: "changed" means different from what arrived, not touched. |
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
| A value changes on an inline card | The panel updates immediately, with no model turn. Trip facts are shared state, not something the agent re-renders. |
| Nothing decided yet | The panel says what the agent is about to ask, rather than showing an empty form. |
| A stage the trip does not need | Struck through and marked *not needed*. Never asked about again. |
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
| Changing a stage that was skipped | It comes back — "actually, we do need a hotel in Madrid" un-skips it. |
| Changing after the trip is finished | The plan reopens at that step. |
| Pressing Change twice | The second is a no-op; it is already released and open inline. |

## Flow 5 · Somewhere to stay

Three cities do not mean three hotels, so this is asked **per stop**: which of
these need a room, and which do not. A friend's spare room, a wedding block, a
red-eye out the same night — all reasons a stop needs nothing.

Answered once per stop and never asked again. Stays are then found only for the
stops that need one.

## Flow 6 · Finishing

When every stage is settled or ruled out, the agent stops asking. It shows the
whole trip on one surface and offers the two things actually left — adding more
to the days, or sharing the plan with whoever else is coming — and wishes them a
good trip.

**Edge case:** a trip that will never be "complete" — someone browsing, someone
who only wanted a fare. The agent does not force the sequence; a stage ruled out
is a stage finished, and one that has not come up is not nagged about.

## Flow 7 · Inside Claude

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
| Editors never send | the renderer, and again in the host | A model that adds an action to a slider should not be able to break the interaction model. |
| Only the newest surface is interactive | the host (`inert`) | The agent has no idea what else is on screen. |
| Trip values pre-fill every surface | the host | Prompting a model to remember state it cannot see is how it forgets. |
| No prices without dates and a route | the tools | A model in a hurry prices a plausible week and calls it a sample. |
| A date range that ends before it starts | the tools | Silent corruption of everything downstream. |
| One surface, one button, ask for everything | the skill | A judgement call about layout, which is the model's job. |
| Say what a price is priced against | the skill, from a value the tools supply | The wording is the model's; the facts are not. |
| Lead the trip; know when to stop | the skill, from the model's plan | Same split: the sequence is computed, the phrasing is not. |

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
