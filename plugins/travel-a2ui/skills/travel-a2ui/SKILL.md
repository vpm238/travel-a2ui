---
name: travel-a2ui
description: Plan trips as interactive surfaces rather than paragraphs — flight cards the traveller picks from, date pickers they set, day plans they tap through. Use whenever someone is choosing flights or stays, setting trip dates or party size, wants an itinerary or a cost breakdown, or asks what a trip would look like. Also use when asked to compose a custom A2UI interface.
---

# Answering in interfaces

You have a travel server that returns **interfaces**, not text. Four fares read
aloud is a memory test; four fare cards is a choice. When a traveller is
deciding something, hand them the thing they decide with.

Call a tool, and the result carries a surface the host draws. You do not
describe the surface afterwards — it is already on screen. Say the one thing
the surface does not: which you would take, and why.

## The tools

| Tool | For |
| --- | --- |
| `show_flight_options` | choosing a flight |
| `show_hotel_options` | choosing somewhere to stay |
| `show_trip_controls` | dates, party size, cabin, budget — anything they set |
| `show_itinerary` | a day-by-day plan |
| `show_trip_dashboard` | where the trip stands, at a glance |
| `show_price_summary` | what it comes to, itemised |
| `render_a2ui_express` | a surface none of the above draws |
| `get_a2ui_component_reference` | the component contract, when you need to write one |

Every tool ships example arguments in its `_meta.example`. When you are unsure
what a call wants, read that rather than guessing.

## Two rules that matter

**Never invent a date, a departure city or a party size.** The server refuses
to price a trip nobody has described, and it is right to: a plausible number
for a week the traveller never chose is worse than a question. When a tool
comes back asking for something, draw `show_trip_controls` bound to what is
missing and let them set it — one surface, one commit button, then continue.

**Say where the numbers came from.** Every result carries `provenance`. On the
public deployment that reads *Sample data*, because the fares are generated;
with a live inventory credential configured it names the source instead. If a
traveller might act on a price, they are owed the label.

A result may also carry `relaxed` — constraints the server widened to have
anything to show, like a price cap nothing matched. Repeat it. "Nothing under
£400 nonstop; the closest is £430 with a stop" is the useful sentence.

## Composing your own surface

`render_a2ui_express` compiles **A2UI Express** — a compact notation for a UI
tree — and the host draws it with the same component library every other tool's
result uses. This is the part worth understanding: the contract is not in this
skill, it is on the server. Call `get_a2ui_component_reference` and you get the
grammar, the streaming rules and the positional signature of every component
and function the deployment currently has.

That is deliberate. A contract copied into a plugin goes stale the moment the
server adds a component; one fetched from the server cannot. Read the reference
when you are about to compose something, not before.

The shape is small enough to recognise:

```
surface("trip-note")
head = Text("Two nights in Lisbon", variant="h2")
a1 = ActivityItem("Alfama at dawn", "07:30", category="sight", note="Before the tour groups")
a2 = ActivityItem("Time Out Market", "11:30", category="food", duration="1h")
day = ItineraryDay("Saturday", [a1, a2], date="Sat 18 Apr")
root = Column([head, day])
```

Named lines, one component each, and a `root` that says what the surface is.
Anything the reference does not define does not exist — a component you invent
fails to compile, and the error comes back to you rather than to the traveller.

## What not to do

- Do not read a list of fares aloud after drawing the cards. They can see them.
- Do not re-draw a surface that is already on screen and still current.
- Do not substitute a city the server does not know for one it does. If it
  cannot place somewhere, it says so and names what it covers — offer those.
- Do not present generated prices as bookable. Nothing here books anything.
