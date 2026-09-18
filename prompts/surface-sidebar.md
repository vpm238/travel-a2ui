## This surface: the panel — what is settled, and nothing else

A persistent panel beside the conversation showing the trip as it stands. It is
**read-only**. Deciding happens in the conversation; this is the record.

- **No editors here.** No slider, no date picker, no counter, no text field, no
  checkbox. The host ignores them anyway, so one in this panel is a control that
  visibly does nothing — worse than not drawing it.
- Show what is *decided*: the route stop by stop, the flight and stay chosen,
  the dates, the party, the budget against what it is estimated to cost.
- **Show it with the component built for it, not with a line of text.** Read-only
  does not mean plain. Every display component in the catalog is available here,
  and a settled decision drawn as the card it deserves is the difference between
  a panel and a receipt:

  - the stay → `HotelCard`, carrying what the search returned: `neighborhood`,
    `rating`, `amenities`, `imageUrl` when there is one, and `selected` set so
    it reads as the chosen one
  - the flight → `FlightOption`, with its times, duration, stops and number
  - the days → `ItineraryDay` with `ActivityItem` children, not a list of
    sentences about the days
  - when they are going → `TripCalendar`, bound to `$/trip/startDate` and
    `$/trip/endDate`, with the flights marked on their days
  - where the stops are → `MapPreview`
  - what it will be like → `WeatherStrip`
  - the money → `PriceSummary`, and `StatTile` for the figures worth a glance
  - `Card`, `Row`, `Column` and `Icon` to arrange it

  Imagery comes from the component that owns it — `HotelCard`'s `imageUrl`,
  `MapPreview`'s markers — rather than from a standalone image component, which
  is not in the catalog you were given.

  These carry **no `action`** in the panel. A card without one is a record: the
  host draws it fully and it does not respond to a press, which is exactly what
  a panel entry should be. The way to re-open a decision is the Change button
  below, and that is the only thing here that a traveler can press.
- **The only button you may draw here is Change**, and its only event is
  `change`. Nothing else. Not a question, not a confirmation, not "add a
  hotel" — if something still needs deciding, that belongs in the conversation
  and you will be asked for it there on the next turn. A button here that is not
  a Change is a button the host ignores, so it sits on screen doing nothing.

  One per decision, naming the trip field:

  ```
  flight = Text("Iberia IB614 · 08:39 → 12:51 · $257")
  changeFlight = Button(Text("Change"), "borderless", Event("change", {field: "selectedFlight"}))
  ```
- Rebuild the whole panel each time. It is one surface, replaced, not appended.
- If nothing is decided yet, say what you are about to ask rather than drawing
  an empty shell.
- Target the surface id `sidebar`.

### The decisions are the panel

The host keeps `/plan` up to date for you — you never compute it, and you never
redraw it when it moves. It is not a progress bar; it is **the record of every
decision, each one addressable so it can be changed**. Bind to it and it stays
right:

- `$/plan/decisions` — the trip's own decisions: where to, from where, the
  dates, the budget. Each row has a `label`, a `value`, a composed `line`, and a
  `key` — the key is what a Change button releases.
- `$/plan/route` — one row per hop, in travelling order. Each has `place`,
  `from`, `nights`, a composed `line`, its own `decisions` rows (who is on that
  hop, its ticket, where they sleep) and `wants` — what that hop is still
  missing.
- `$/plan/caption` — "7 decided · 3 hops · 2 open"
- `$/plan/multiStop` — true when the route is worth drawing as a route

A hop's decision keys are scoped to the hop: `legs/1/travelers`, not
`travelers`. Pass the row's own `key` through and a correction changes that hop
rather than undoing the answer on another.

### Do not draw the decisions with a template

A template row is **one** component. It cannot hold a label and a Change button
side by side, so a templated list of decisions can have rows or it can have
Change — never both. Reach for `List(_template(…))` here and what you produce is
a record of somebody's trip that they cannot correct: it looks right and every
row is inert.

So write the decision rows out, one per decision, each with its own button:

```
d0t = Text("where you are going — Madrid")
d0b = Button(Text("Change"), "borderless", Event("change", {field: "destination"}))
d0  = Row([d0t, d0b], justify="spaceBetween", align="center")

d1t = Text("when you are leaving — 12 Apr")
d1b = Button(Text("Change"), "borderless", Event("change", {field: "startDate"}))
d1  = Row([d1t, d1b], justify="spaceBetween", align="center")

root = Column([head, d0, d1], align="stretch")
```

Read the rows out of `$/plan/decisions` and write one group per row, using that
row's own `line` for the text and that row's own `key` for the field. There are
rarely more than a dozen. The same for `$/plan/route`: the hop's `line` as a
heading, then a group per entry in that hop's `decisions`, whose keys are
already scoped — `legs/1/travelers`.

`_template` is still the right tool where a row has **nothing to press**: a list
of activities, a set of fares you have not offered an action on. The rule is
simply that Change cannot live inside one.

Draw both, every time you build the panel: the decisions, then the route. That
is the traveler's answer to "what have I actually said, and what is left on each
leg", and it is the reason this reads as a planner rather than a chat that
happens to draw cards.
