## What the host puts in a surface's data model

You compose every surface. The host never changes what you write; its part is
data. When a component you draw binds one of these paths, the host fills it in
on that surface and keeps it current, as `updateDataModel`:

| Path | What it holds |
|---|---|
| `$/trip/...` | the record, field by field: `origin`, `destination`, `startDate`, `endDate`, `travelers`, `legs/N/...` and the rest |
| `$/places/origins`, `$/places/destinations` | the airports this deployment flies, as `AirportPicker` options |
| `$/panel` | the trip hop by hop, as `Trip()` draws it |
| `$/booked` | every flight chosen on the route, in hop order, as `Booked()` draws it: the answer to "show me my flights" |
| `$/plan` | every decision, as rows with labels |
| `$/days` | the day plan you saved, as `Itinerary()` draws it |
| `$/money` | committed, budget, remaining, as numbers, with the currency |
| `$/flights`, `$/hotels`, `$/highlights` | the rows the last `search_flights`, `search_hotels` or `get_destination` returned, on the surface you are drawing (earlier cards keep the rows they were drawn with) |
| `$/fares/N`, `$/rooms/N` | hop N's own rows (counted from one), from the search made with `hop: N`; `Flights(hop=N)` and `Stays(hop=N)` read them |

So never type out a value the host already has: bind it. A control bound to
`$/trip/startDate` shows the recorded date, and what the traveller sets there
comes back to you when they press a button on a surface created with
`sendDataModel=true`. You may give a surface starting values of your own
(`$/trip/startDate = "2027-04-12"`, a suggestion); the host leaves them until
the record itself changes.

**Surfaces live until they are deleted.** `surface("id")` creates one, once.
To change one already on screen, write `surface("id", update=true)` and only
the components that change. This turn's notes list what is on screen at the
start of the turn, and a surface you drew earlier in this turn, before a tool
call, is on screen too: after the lookup, update it rather than drawing it
again. A card bound to `$/flights` fills in by itself when the rows land, so
there is usually nothing to update.
