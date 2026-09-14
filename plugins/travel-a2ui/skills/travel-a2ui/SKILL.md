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

Nine for data, two for drawing. Nothing here returns a finished layout — you
compose those, which is the point of the plugin.

| Tool | For |
| --- | --- |
| `search_flights` | fares, times and stops for a hop |
| `search_hotels` | nightly rates, neighbourhoods, ratings |
| `get_destination` | what is worth doing, when to go, the local currency |
| `get_weather` | a short forecast by day |
| `estimate_cost` | the trip itemised, hop by hop and stay by stay |
| `save_trip` | record what they have decided |
| `release_decision` | let go of one, and whatever depended on it |
| `get_trip` | read the whole trip back |
| `share_plan` | the trip as a page somebody outside the chat can read |
| `get_a2ui_component_reference` | the component contract, before you write one |
| `render_a2ui_express` | compile a surface and draw it |
| `export_a2ui_app` | the same surface as a standalone page, for a host that cannot draw one |

There used to be six `show_*` tools here that each returned a finished card —
flights, hotels, controls, itinerary, dashboard, a price summary. They are gone
from the listing on purpose. Given both paths a capable host takes the one-call
path every time, because it is one call, and the generative path never runs. A
demo whose whole argument is that a model composes interfaces spent its life
picking from a menu of six.

Every tool ships example arguments in its `_meta.example`. When you are unsure
what a call wants, read that rather than guessing.

## When nothing appears on screen

Call `render_a2ui_express` first. Its result carries the surface *and*
`_meta.ui.resourceUri`, and a host that implements MCP Apps fetches that
resource and draws the interface in a frame. That is the good path and it costs
one small call.

**Not every host does that.** Some show you the tool result as text. If you can
see the A2UI JSON in your own transcript rather than an interface, that is what
happened — and describing the interface in prose is the one thing this plugin
exists to stop you doing.

So use `export_a2ui_app` instead. It returns **one HTML file with the renderer
baked into it**: the same React components, nothing to fetch. Write it to a
`.html` file and open it, or publish it however your host publishes generated
pages. The interface appears.

It carries the renderer rather than linking it for a specific reason. A host
that sandboxes generated HTML usually allows scripts only from a short list of
public CDNs, and this deployment is not one of them — so a page that *links*
`/mcp-view/app.js` draws nothing at all, silently, with the reason in a console
nobody opens. A page that carries it has nothing to be blocked.

The cost is size: about 250 kB, nearly all of it the renderer. So reach for it
when you need the page, not for every turn — and never twice for the same
surface.

```
get_a2ui_component_reference     once, for the grammar and the signatures
search_flights / search_hotels   the real numbers
export_a2ui_app                  the page, if the host will not draw one itself
```

## Two rules that matter

**Never invent a date, a departure city or a party size.** The server refuses
to price a trip nobody has described, and it is right to: a plausible number
for a week the traveller never chose is worse than a question. When a tool
comes back asking for something, compose one surface bound to what is missing —
a `ChoicePicker` of airports, a `DateRangePicker`, a `TravelerCounter`, one
commit button carrying all of it — and let them set it, then continue. A
`TextField` for a date is a date they can get wrong.

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
