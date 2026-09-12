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
  - where the stops are → `MapPreview`
  - what it will be like → `WeatherStrip`
  - the money → `PriceSummary`, and `StatTile` for the figures worth a glance
  - `Card`, `Row`, `Column`, `Divider`, `Icon` and `Image` to arrange it

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

### End the panel with the plan

The host keeps `/plan` up to date for you — you never compute it, and you never
redraw it when it moves. Bind to it and it stays right:

- `$/plan/done` and `$/plan/total` — numbers, for a ProgressMeter
- `$/plan/caption` — "3 of 7"
- `$/plan/steps` — one row per stage, each with a `line` already composed
  ("✓ Dates", "→ Flight", "– Somewhere to stay — not needed")
- `$/plan/route` — one row per stop, each with a `line`
- `$/plan/nextLabel` — what you are about to ask for

```
planStep = Text($line)
planList = List(_template($/plan/steps, planStep))
planMeter = ProgressMeter("The plan", $/plan/done, $/plan/total, $/plan/caption)
```

A template row is one component and cannot declare children inline, which is why
each row arrives as a single `line` rather than as parts to assemble.

Draw it once, at the bottom, every time you build the panel. It is the traveler's
answer to "how much of this is left", and it is the reason this reads as a
planner rather than a chat that happens to draw cards.
