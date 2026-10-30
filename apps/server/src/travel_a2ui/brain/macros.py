"""Components the model writes in one line and the host expands into many.

A macro is a component the catalog advertises and no renderer ever sees: the
model writes `Itinerary()`, and before the surface goes out the host replaces
that node with the day plan it already holds — four `ItineraryDay`s, twelve
`ActivityItem`s, every field filled in.

**It is here for latency, and the latency is output tokens.** The day plan is
the largest thing this agent writes, and until now it wrote it twice: once into
`save_trip({days: […]})`, because a plan that lives only on a card cannot be
shared or edited or survive the turn, and once again as components, because the
card had to be drawn. The second copy is the same data in a different notation,
and it is about eight hundred tokens the traveller waits through — measured at
25.8 seconds for the interface alone on a four-day trip.

The macro removes the second copy. The model records the days and then says
`Itinerary()`.

**Why this is not the host deciding what to draw.** The agent chooses whether
to draw an itinerary at all, when, with what heading, and beside what else. It
can still write `ItineraryDay` and `ActivityItem` by hand, and should when it
wants something this does not do — they stay in the catalog. What the macro
takes away is re-typing data the agent itself recorded one tool call ago. The
host is not choosing the content; it is the agent's own `days`, read back.

The expansion runs per turn against that turn's trip, which is what `for_trip`
carries. A macro function is a plain function to the SDK, so the trip reaches
it through a context variable rather than an argument the model could pass.
"""

from __future__ import annotations

import contextvars
import json
from typing import Any, Optional, Sequence

from a2ui.builder.core import ComponentBuilderNode
from a2ui.builder.v0_9.catalogs.basic import Button, ChildList, Column, List as ListC, Text
from a2ui.builder.v0_9.models import Action, ActionEvent
from a2ui.builder.v0_9.models import DynamicChildList
from a2ui.transformers.macros import MacroExpander, macro

#: Where the two lookups file their rows, read by the macros below and by the
#: host when a tool comes back. Named in the brief too, which is the only
#: coupling left between the two sides.
FLIGHTS = "/flights"
STAYS = "/hotels"
HIGHLIGHTS = "/highlights"

#: The trip the current turn is expanding against.
#:
#: A `ContextVar` rather than a module global because turns run concurrently —
#: two travellers on one instance — and a global would hand one of them the
#: other's day plan. Context variables are per-task, so each turn's expansion
#: sees its own.
_TRIP: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("trip", default={})


#: The airports this deployment can offer, for the pickers `Ask()` draws.
#:
#: Here rather than passed as a macro argument because `ChoicePicker.options`
#: is a static array in the schema — not a `DynamicStringList` — so the choices
#: have to exist when the macro expands, not when the surface renders. And the
#: agent cannot supply them: it would have to call a tool to find out what this
#: provider flies, on the one turn where it already has the least to go on.
#:
#: Shape: `{"from": [{"value": "CPH", "label": "Copenhagen · CPH"}, …], "to": […]}`
_AIRPORTS: contextvars.ContextVar[dict[str, list[dict[str, str]]]] = contextvars.ContextVar(
    "airports", default={}
)


class for_trip:
    """Expand this turn's macros against this trip, and this deployment's airports."""

    def __init__(
        self, trip: dict[str, Any], airports: dict[str, list[dict[str, str]]] | None = None
    ) -> None:
        # The dict itself, not a copy: a turn mutates its trip in place as
        # tools run, and a macro has to see the `days` that `save_trip` wrote
        # a moment ago rather than the trip as it was when the turn began.
        self._trip = trip if isinstance(trip, dict) else {}
        self._airports = airports if isinstance(airports, dict) else {}
        self._tokens: list[Any] = []

    def __enter__(self) -> "for_trip":
        self._tokens = [_TRIP.set(self._trip), _AIRPORTS.set(self._airports)]
        return self

    def __exit__(self, *_: Any) -> None:
        for var, token in zip((_TRIP, _AIRPORTS), self._tokens):
            var.reset(token)


class ActivityItem(ComponentBuilderNode):
    """One scheduled thing: a meal, a museum, a transfer, a check-in."""

    component: str = "ActivityItem"
    title: str
    time: Optional[str] = None
    category: Optional[str] = None
    location: Optional[str] = None
    duration: Optional[str] = None
    note: Optional[str] = None
    done: Optional[bool] = None
    onRemove: Optional[dict[str, Any]] = None


class ItineraryDay(ComponentBuilderNode):
    """One day of the plan, and the things in it."""

    component: str = "ItineraryDay"
    title: str
    children: ChildList
    date: Optional[str] = None
    summary: Optional[str] = None
    onAdd: Optional[dict[str, Any]] = None


def _event(name: str, context: dict[str, Any]) -> dict[str, Any]:
    return {"event": {"name": name, "context": context}}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


@macro
def itinerary(heading: str = "") -> Column:
    """The day plan already recorded on this trip, drawn in full.

    Write it once in `save_trip({days: [...]})` and then draw it with this,
    rather than writing every day and every activity a second time as
    components. Pass a heading to put a line of your own above it.

    Args:
        heading: Optional line above the plan, e.g. 'Four days in Berlin'.
    """
    trip = _TRIP.get()
    days = trip.get("days")
    rows: list[Any] = []
    drew_a_day = False
    if isinstance(heading, str) and heading.strip():
        rows.append(Text(text=heading, variant="h3"))

    for index, day in enumerate(days if isinstance(days, list) else []):
        if not isinstance(day, dict):
            continue
        activities = [
            ActivityItem(
                title=_text(activity.get("title")),
                time=activity.get("time"),
                category=activity.get("category"),
                location=activity.get("location"),
                duration=activity.get("duration"),
                note=activity.get("note"),
                done=activity.get("done"),
                # Every activity gets one: a day plan is the traveller's to
                # edit, and `drop_activity` edits the trip rather than the card.
                onRemove=_event("drop_activity", {"day": index, "index": position}),
            )
            for position, activity in enumerate(day.get("activities") or [])
            if isinstance(activity, dict)
        ]
        drew_a_day = True
        rows.append(
            ItineraryDay(
                title=_text(day.get("title")) or f"Day {index + 1}",
                date=day.get("date"),
                summary=day.get("summary"),
                children=activities,
                onAdd=_event("add_activity", {"day": index}),
            )
        )

    if not drew_a_day:
        # Nothing recorded yet. Saying so is better than an empty box, and
        # better than refusing to compile a surface the traveller is waiting
        # for: the agent's prose above it still arrives.
        #
        # Counted rather than inferred from `rows` being empty, because a
        # heading is a row: `Itinerary("Four days in Berlin")` over a trip with
        # no days would otherwise draw the promise and nothing under it.
        rows.append(Text(text="No day plan recorded yet."))

    return Column(children=rows)


# --------------------------------------------------------------------------
# The two lists a lookup fills
# --------------------------------------------------------------------------
#
# `Flights()` and `Stays()` exist for the same reason `Itinerary()` does, and
# they replace the last piece of host-drawn UI in the app.
#
# The host used to compile Express for a fare list itself, paint it the moment a
# lookup started, and tell the model "do not draw this surface again". That is
# the interface decided in Python. Writing the list out by hand instead — a
# bound `FlightOption` under a `_template`, with a `formatString` label — is
# three hundred tokens the traveller waits through, every search, and the model
# would not spend them before a lookup it had not run yet.
#
# As a macro it is nine characters. The agent decides whether there is a list,
# what is above it, which hop the press names and where the choice is recorded;
# the host writes out the part that is the same every time. And because it is
# nine characters, writing it *before* the tool call costs nothing — which is
# the whole of why the interface can be on screen while the lookup runs.
#
# Bound, never literal: every field is a path into the rows `file_rows` puts at
# `/flights` or `/hotels`, so the card fills in as they land and cannot
# disagree with what was found.


class FlightRow(ComponentBuilderNode):
    """One fare, with every field bound to the row being drawn."""

    component: str = "FlightOption"
    airline: Any = None
    departTime: Any = None
    arriveTime: Any = None
    origin: Any = None
    destination: Any = None
    price: Any = None
    action: Any = None
    duration: Any = None
    stops: Any = None
    flightNumber: Any = None
    cabin: Any = None
    total: Any = None
    badge: Any = None
    selected: Any = None
    accessibility: Any = None


class HighlightRow(ComponentBuilderNode):
    """One thing a destination is worth going for, bound the same way.

    `category` is missing on purpose: it picks the icon and the colour, and the
    schema keeps it a plain string rather than a `DynamicString`, so it cannot
    be bound to a row. The rows carry one anyway and a later turn's hand-written
    `ActivityItem` can use it; what this draws is the three fields that are
    bindable, and the host's default icon.
    """

    component: str = "ActivityItem"
    title: Any = None
    note: Any = None
    location: Any = None
    duration: Any = None
    action: Any = None
    accessibility: Any = None


class StayRow(ComponentBuilderNode):
    """One stay, bound the same way."""

    component: str = "HotelCard"
    name: Any = None
    price: Any = None
    action: Any = None
    imageUrl: Any = None
    neighborhood: Any = None
    rating: Any = None
    amenities: Any = None
    badge: Any = None
    selected: Any = None
    accessibility: Any = None


def bind(path: str) -> dict[str, str]:
    """A binding to that pointer, spelled the way this protocol spells it.

    `brain.bindings` owns that decision and this cannot import it: `bindings`
    reads `catalog`, `catalog` builds the inference catalog from this module,
    and the cycle closes. Asserted equal to it in the tests instead, which is
    the honest way to hold two copies of one decision together.
    """
    from .bindings import PATH_KEY

    return {PATH_KEY: path}


def _reads(*fields: str) -> dict[str, Any]:
    """A label that reads the row aloud as a sentence.

    `formatString` resolves against the row being drawn, so one component names
    however many rows arrive. A card read in field order is "Iberia IB6250
    18:40 JFK 08:15 +1 MAD 7h 35m Nonstop $412" — every fact and no sentence —
    and `accessibility.label` replaces that rather than adding to it.
    """
    return {"label": {"@call": "formatString", "args": {"value": " ".join(fields)}}}


def _hop(value: Any) -> Optional[int]:
    """Whichever hop the agent meant, as a number, or nothing.

    The signature says `int` and the SDK does not enforce it, so `Flights("Back
    · MAD → JFK", "", "2")` arrives as a string — which is a thing the model
    writes, and it used to raise `'>' not supported between instances of 'str'
    and 'int'` inside the expander. The expander catches that and reports
    "Failed to expand macro 'Flights'", so the whole fare list silently did not
    draw: the traveller got prose about four flights and no cards, and the only
    trace was one line in the server log.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        # Through `float` so that `2.0` and `"2.0"` are hop two rather than
        # nothing. A hop silently lost is the return overwriting the outbound.
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else None


def _context(hop: Any, **fields: Any) -> dict[str, Any]:
    """A press's context, naming its hop when it is not the first.

    Hop two is `legs[0]`, and a fare offered for any hop but the first has to
    say which — without it the only field that fits is the trip's own
    `selectedFlight`, and the return overwrites the outbound.
    """
    number = _hop(hop)
    if number is not None and number > 1:
        return {**fields, "hop": number}
    return fields


@macro
def flights(heading: str = "", selected: str = "", hop: Any = None) -> Column:
    """The fares a lookup filed, as a list the traveller can press.

    Write this instead of a fare card per result. `search_flights` puts its rows
    at `/flights` and this reads them, so it can go on screen *before* the
    lookup — draw it, then call the tool, and it fills in as the rows land.

    Args:
        heading: Optional line above the list, e.g. 'Outbound · JFK → MAD'.
        selected: Data path holding the current choice, e.g.
            '/trip/selectedOutbound', so the chosen card stays marked.
        hop: Which hop these fares are for, when it is not the first. Hop two
            is '/legs/0'; the press carries it so the fare lands on that leg.
    """
    row = FlightRow(
        airline=bind("airline"),
        departTime=bind("departTime"),
        arriveTime=bind("arriveTime"),
        origin=bind("origin"),
        destination=bind("destination"),
        price=bind("price"),
        action={
            "event": {
                # The id and the price *and* what the fare is.
                #
                # It used to carry only `{id, price}`, so the trip learned that
                # SK8495 cost €69 and nothing else — and the panel, which is
                # bound to the record, had nothing to show but the price. That
                # is the whole of why the sidebar read as a card still loading:
                # there was no airline to load.
                "name": "select_flight",
                "context": _context(
                    hop,
                    id=bind("id"),
                    price=bind("price"),
                    airline=bind("airline"),
                    departTime=bind("departTime"),
                    arriveTime=bind("arriveTime"),
                ),
            }
        },
        duration=bind("duration"),
        stops=bind("stops"),
        flightNumber=bind("flightNumber"),
        # What the whole party pays, when that is a different number from the
        # fare. A row without one resolves to nothing and the card falls back
        # to the cabin, which is what every single-traveller trip wants.
        total=bind("total"),
        badge=bind("badge"),
        selected=bind(selected) if selected else None,
        # `${total}` last and unpunctuated: it resolves to nothing on a
        # single-traveller row, and to "$1,978 for 2" on a row that carries
        # one, so the sentence reads correctly either way without the host
        # writing two versions of it.
        accessibility=_reads(
            "${airline} ${flightNumber},",
            "${departTime} ${origin} to ${arriveTime} ${destination},",
            "${stops}, ${price} ${total}",
        ),
    )
    rows: list[Any] = []
    if isinstance(heading, str) and heading.strip():
        rows.append(Text(text=heading, variant="h3"))
    rows.append(ListC(children=DynamicChildList(path=FLIGHTS, template=row)))
    return Column(children=rows)


@macro
def stays(heading: str = "", selected: str = "", hop: Any = None) -> Column:
    """The stays a lookup filed, as a list the traveller can press.

    `search_hotels` puts its rows at `/hotels`. Same shape as `Flights()`: draw
    it, then call the tool.

    Args:
        heading: Optional line above the list, e.g. 'Stays in Madrid'.
        selected: Data path holding the current choice, e.g.
            '/trip/selectedHotel'.
        hop: Which hop is staying the night, when it is not the first.
    """
    row = StayRow(
        name=bind("name"),
        price=bind("price"),
        action={
            "event": {
                # This one already carried the name; what it lacked was a place
                # on the trip to put it. See `hotelName` in `trip-model.json`.
                "name": "select_hotel",
                "context": _context(
                    hop, id=bind("id"), name=bind("name"), price=bind("price")
                ),
            }
        },
        neighborhood=bind("neighborhood"),
        rating=bind("rating"),
        amenities=bind("amenities"),
        badge=bind("badge"),
        selected=bind(selected) if selected else None,
        accessibility=_reads("${name}, ${neighborhood},", "rated ${rating}, ${price}"),
    )
    rows: list[Any] = []
    if isinstance(heading, str) and heading.strip():
        rows.append(Text(text=heading, variant="h3"))
    rows.append(ListC(children=DynamicChildList(path=STAYS, template=row)))
    return Column(children=rows)


@macro
def highlights(heading: str = "") -> Column:
    """What a destination is worth going for, as the lookup filed it.

    `get_destination` puts its highlights at `/highlights` and this reads them,
    so it goes on screen *before* the lookup — draw it, then call the tool.

    This is the one card to draw on a planning turn, and the reason is the
    clock. Writing a four-day plan into `save_trip` is the longest thing you
    say, and nothing about the plan is known until it is written, so there is
    nothing to promise: the traveller waited twenty-four seconds at a blank
    space. The city's own highlights are known a great deal sooner, they are
    what the plan is going to be built out of, and they are worth reading on
    their own. Draw them, write the plan, then draw `Itinerary()`.

    Args:
        heading: Optional line above the list, e.g. 'Worth your time in Berlin'.
    """
    row = HighlightRow(
        title=bind("name"),
        note=bind("note"),
        accessibility=_reads("${name}, ${note}"),
    )
    rows: list[Any] = []
    if isinstance(heading, str) and heading.strip():
        rows.append(Text(text=heading, variant="h3"))
    rows.append(ListC(children=DynamicChildList(path=HIGHLIGHTS, template=row)))
    return Column(children=rows)


# --------------------------------------------------------------------------
# And the host's share: the rows themselves
# --------------------------------------------------------------------------
#
# Beside the macros that read them, so the two cannot drift. An address is
# state; what reads it is the agent's business.

#: Where each lookup's rows are filed, and the key they arrive under.
LANDINGS: dict[str, tuple[str, str]] = {
    "search_flights": (FLIGHTS, "flights"),
    "search_hotels": (STAYS, "hotels"),
    # The one lookup on the planning half of the trip with a shape worth
    # promising. It is also the turn that most needed one: writing a four-day
    # plan into `save_trip` is the largest thing this agent says, and until the
    # destination's own highlights could go up against it the traveller watched
    # 23.9 seconds of nothing. These are real content rather than a placeholder
    # — what the city is worth going for, while the plan that uses them is
    # being written.
    "get_destination": (HIGHLIGHTS, "highlights"),
}


#: Which macro draws each lookup's rows, and which `draw:` keys it takes.
#:
#: A tautology rather than a decision: `search_flights` draws `Flights()`. The
#: keys are listed because the macros do not take the same arguments — a list of
#: fares has a hop and somewhere to record the choice; a city's highlights have
#: neither, and passing it an empty `selected` would be a second positional
#: argument the macro does not accept.
DRAWN_BY: dict[str, tuple[str, tuple[str, ...]]] = {
    "search_flights": ("Flights", ("heading", "selected", "hop")),
    "search_hotels": ("Stays", ("heading", "selected", "hop")),
    "get_destination": ("Highlights", ("heading",)),
}


#: The same thing for a tool whose card can only be drawn *after* it runs.
#:
#: `save_trip` is the one, and the reason is that `Itinerary()` reads the trip
#: rather than a data path: drawn at dispatch it would say "no day plan recorded
#: yet", because the days are in the arguments and have not been applied.
#:
#: So this is not here to put a card up early — it is here to spend one model
#: round instead of two. A planning turn used to end like this: twenty seconds
#: writing the plan into `save_trip`, the tool returns, and then a whole further
#: round — 16.7 seconds, 1,158 thought tokens — to emit `Itinerary()` and one
#: sentence. The macro had already done its job; the round was the cost. With
#: the heading in the call that wrote the plan, the card lands when `save_trip`
#: returns and what is left to say is the sentence.
#: `save_trip` is the only tool here, and it can draw either of two cards,
#: because the two slowest turns in the app both end in a write.
#:
#: The opening turn is the one that hurt most. Nothing is known, so there is no
#: lookup to draw ahead of, and the agent's own `Ask()` block arrives only
#: after it has finished thinking — measured at 21.4 seconds to a first
#: interface, against 6 to 12 for a turn that searches. But the write happens
#: at 10.8s, and the form it should draw is the same `Ask()` either way. So the
#: agent names the card in the call that records what it just learned.
DRAWN_AFTER: dict[str, dict[str, tuple[str, ...]]] = {
    "save_trip": {
        "Itinerary": ("heading",),
        "Ask": ("heading", "label"),
    },
}


def airport_choices(
    origins: Sequence[dict[str, Any]], destinations: Sequence[dict[str, Any]]
) -> dict[str, list[dict[str, str]]]:
    """The provider's two lists, as `ChoicePicker` options for `Ask()`.

    Pure, and takes the lists rather than the provider, so the awaiting happens
    once in the door and this stays testable without one.

    Labelled "Copenhagen · CPH" both ways, because a traveller knows the city
    and may not know the code. What each one *stores* differs, and follows the
    field rather than the control: `origin` is "three-letter code", so the
    option stores CPH; `destination` is "city or airport", and the city is what
    the panel heading, the prose and every later lookup read better — a trip
    stored as "→ MAD" says MAD everywhere a person expects Madrid.
    """

    def label(code: Any, city: Any) -> str:
        code, city = str(code or "").strip(), str(city or "").strip()
        return f"{city} · {code}" if city and code else city or code

    out: dict[str, list[dict[str, str]]] = {"from": [], "to": []}
    for entry in origins or ():
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip()
        if code:
            out["from"].append({"value": code, "label": label(code, entry.get("city"))})
    for entry in destinations or ():
        if not isinstance(entry, dict):
            continue
        city = str(entry.get("city") or "").strip()
        code = str(entry.get("airport") or "").strip()
        if city or code:
            out["to"].append({"value": city or code, "label": label(code, city)})
    return out


def _macro_call(
    table: dict[str, tuple[str, tuple[str, ...]]], tool: str, draw: Any, surface_id: str
) -> str:
    """The surface the agent asked for in a tool call, as Express.

    This is the answer to a question two prompt rewrites could not settle.
    Drawing before the lookup is strictly better — the traveller watches an
    interface fill in instead of waiting at a blank space — and the agent would
    only do it on the opening turn. On any turn answering a press it records the
    decision and searches in the *same* round of tool calls, which is right, and
    leaves no gap to emit a block into.

    So the agent says what to draw in the call itself: `search_flights(...,
    draw: {heading: "Outbound · JFK → MAD", selected: "/trip/selectedOutbound"})`.
    One act, no ordering to get wrong, and the host draws it the moment the
    lookup starts.

    Still the agent's interface in every respect that decides anything: whether
    there is a list at all, what is above it, where the choice is recorded, and
    which hop the press names. What the host contributes is expanding a macro
    out of the agent's own vocabulary — the same `Flights()` it writes by hand
    when it wants the list somewhere else.

    `table` is which side of the tool call the card belongs on: `DRAWN_BY` for a
    lookup whose shape is known before it runs, `DRAWN_AFTER` for one whose
    macro reads the trip and so has to wait for the write to land.

    Returns Express rather than messages because compiling needs the parser,
    and the parser needs the catalog, which is built from this module.
    """
    found = table.get(tool)
    if not found or not isinstance(draw, dict):
        return ""
    macro, takes = found
    # `ensure_ascii=False`, or a heading with a `·` in it — which is every
    # heading this app writes — reaches the compiler as `\u00b7`.
    def quoted(value: Any) -> str:
        return json.dumps(value if isinstance(value, str) else "", ensure_ascii=False)

    args: list[str] = []
    for key in takes:
        value = draw.get(key)
        if key == "hop":
            # Only when it is not the first: hop one is the trip's own fields,
            # and saying so would send the press looking for `legs[-1]`.
            if isinstance(value, int) and value > 1:
                args.append(str(value))
            continue
        args.append(quoted(value))
    # Trailing empties only repeat the macro's own defaults. Dropping them from
    # the end — never the middle — keeps `Flights("", "/trip/selectedOutbound")`
    # addressing `selected` by position while `Highlights()` stays nine
    # characters, which is the whole reason a turn will spend them.
    while args and args[-1] == '""':
        args.pop()
    return "\n".join(
        [
            f"surface({json.dumps(surface_id, ensure_ascii=False)})",
            f"rows = {macro}({', '.join(args)})",
            "root = Column([rows])",
        ]
    )


def opening_express(tool: str, draw: Any, surface_id: str) -> str:
    """What to draw the moment a lookup starts. See `_macro_call`."""
    return _macro_call(DRAWN_BY, tool, draw, surface_id)


def closing_express(tool: str, draw: Any, surface_id: str) -> str:
    """What to draw the moment a write lands. See `_macro_call` and `DRAWN_AFTER`.

    Unlike a lookup, a write does not imply its own card — `save_trip` records
    a date as readily as a four-day plan — so the agent names the macro and
    this refuses anything that is not one of the two it may name.
    """
    offers = DRAWN_AFTER.get(tool)
    if not offers or not isinstance(draw, dict):
        return ""
    wanted = str(draw.get("macro") or "").strip()
    takes = offers.get(wanted)
    if takes is None:
        return ""
    return _macro_call({tool: (wanted, takes)}, tool, draw, surface_id)


def landing_for(tool: str) -> Optional[str]:
    """The path this lookup's rows land at, if it is one the host files."""
    found = LANDINGS.get(tool)
    return found[0] if found else None


def rows_in(tool: str, result: Any) -> Optional[list[Any]]:
    """The rows in a lookup's result, or nothing when it found none.

    `None` rather than `[]`, and the two are different answers: a refusal — no
    dates, a destination nobody has heard of — comes back as a result with no
    rows in it, and filing an empty array over whatever is on screen would blank
    a card the traveller is reading.
    """
    found = LANDINGS.get(tool)
    if not found or not isinstance(result, dict):
        return None
    rows = result.get(found[1])
    return rows if isinstance(rows, list) and rows else None


#: How many placeholder rows a pre-drawn list stands up while its lookup runs.
#:
#: Three, because the point is to show the *shape* and the shape is "a few of
#: these". Enough that the list reads as a list; few enough that a lookup
#: returning two does not visibly shrink it.
SEEDED_ROWS = 3


def seed_rows(tool: str, surface_id: str, version: str) -> list[dict[str, Any]]:
    """Blank rows at the landing path, so a pre-drawn list has something to be.

    This is the half of drawing-before-the-lookup that was missing, and without
    it the other half did nothing a traveller could see: `Flights()` is one
    `ActivityItem`-style template over `/flights`, and a template over an empty
    array iterates nothing. The card went up at 9 seconds and rendered as
    blank space until the rows landed — which is the wait it was added to fix.

    A blank row is `{}`. Every bound field on the template then fails to
    resolve, and the renderer's own rule turns that into the shimmer: "a path
    that does not resolve is pending, a path that resolves to an empty string
    is empty" (`renderers/react/src/binding.ts`). So no protocol, no loading
    flag, no second component — the skeleton is the real card with no data in
    it yet, which is also why it cannot drift from the real card.

    Paired with `clear_rows`: a lookup that found nothing has to take these
    away, or the placeholder shimmers for ever and becomes the bug it replaced.
    """
    path = landing_for(tool)
    if path is None:
        return []
    return [
        {
            "version": version,
            "updateDataModel": {
                "surfaceId": surface_id,
                "path": path,
                "value": [{} for _ in range(SEEDED_ROWS)],
            },
        }
    ]


def clear_rows(tool: str, surface_id: str, version: str) -> list[dict[str, Any]]:
    """Take the placeholders away, for a lookup that came back with nothing.

    The one case where filing `[]` is right. Everywhere else it would blank a
    card the traveller is reading, which is why `rows_in` answers `None` rather
    than `[]` for a refusal — but rows this host seeded three seconds ago are
    not something anybody is reading, and leaving them shimmering says "still
    looking" for ever about a search that is over.
    """
    path = landing_for(tool)
    if path is None:
        return []
    return [
        {
            "version": version,
            "updateDataModel": {"surfaceId": surface_id, "path": path, "value": []},
        }
    ]


def file_rows(tool: str, result: Any, surface_id: str, version: str) -> list[dict[str, Any]]:
    """A lookup's rows, at their address. The host's whole share of a search.

    One `updateDataModel` and no components. The surface need not exist yet —
    the renderer creates one for a data update that arrives first — so this
    works whether the agent drew its list before the lookup or after it.
    """
    rows = rows_in(tool, result)
    path = landing_for(tool)
    if rows is None or path is None:
        return []
    return [
        {
            "version": version,
            "updateDataModel": {"surfaceId": surface_id, "path": path, "value": rows},
        }
    ]


# --------------------------------------------------------------------------
# The panel
# --------------------------------------------------------------------------
#
# `Trip()` is the standing panel, and it exists to make the panel *reliable*
# rather than merely possible.
#
# It was a second model call. Values reached the panel live, but a decision
# that gave it something it had no room for — the first fare chosen, a second
# hop — changed its `decision_shape`, and a shape change meant redrawing it:
# another interaction, another copy of the 21,000-token prompt, run after the
# turn had finished. Measured in a browser, 24.8 seconds between pressing a
# fare and the sidebar moving, and 35.4 for the second press.
#
# Letting the agent redraw it in-turn made that possible and not reliable: it
# did not take the instruction up, the host's rebuild fired every time, and the
# walkthrough grew four extra model turns and six thousand output tokens.
#
# So the panel is drawn **complete**. Every slot a decision could fill is
# already there, bound to the record — including the ones still empty — so a
# press only ever changes data, which the host propagates with no model in the
# path. One shape per route, and the route is what the agent is holding when it
# writes `Trip()`.


class PanelFlight(ComponentBuilderNode):
    """A hop's chosen fare, bound to that hop's own fields."""

    component: str = "FlightOption"
    airline: Any = None
    departTime: Any = None
    arriveTime: Any = None
    origin: Any = None
    destination: Any = None
    price: Any = None
    action: Any = None
    flightNumber: Any = None
    selected: Any = None
    accessibility: Any = None


@macro
def trip(heading: str = "") -> Column:
    """The trip as it stands, as the standing panel draws it.

    One section per hop of the route the trip currently has, every value bound
    to the record so that what the traveller settles next arrives without
    another turn. Write it on the panel — `surface("sidebar")` — and nothing
    needs to redraw it again.

    Args:
        heading: Optional line at the top, e.g. 'Your trip to Madrid'.
    """
    from . import trip as model

    record = _TRIP.get()
    rows: list[Any] = []
    if isinstance(heading, str) and heading.strip():
        rows.append(Text(text=heading, variant="h3"))

    hops = model.journey(record) if isinstance(record, dict) else []
    if not hops:
        # Nothing settled yet. A panel saying so is better than an empty box,
        # and better than refusing to draw a surface somebody is looking at.
        rows.append(Text(text="Nothing settled yet."))
        return Column(children=rows)

    for hop in hops:
        if not isinstance(hop, dict):
            continue
        index = hop.get("hop") or 0
        # Hop one owns the trip's own fields; every hop after it owns its leg.
        prefix = "" if index == 0 else f"legs/{index - 1}/"
        where = f"{hop.get('from') or ''} → {hop.get('to') or ''}"
        rows.append(Text(text=where.strip(" →"), variant="h4"))

        # Does *this* hop know this fact?
        #
        # Read off the record rather than off `hop`: `journey` reports what a
        # hop needs and which decisions it has, and does not carry these — so
        # asking it returned nothing for every hop and every card lost its
        # airline, including the one that had it.
        def has(field: str, _at: int = index) -> bool:
            if _at == 0:
                return bool(record.get(field))
            legs = record.get("legs")
            leg = legs[_at - 1] if isinstance(legs, list) and len(legs) >= _at else None
            return bool(isinstance(leg, dict) and leg.get(field))

        def shown(field: str) -> Any:
            """A binding when this hop has the fact, an empty literal when not.

            Not *absent*: the catalog makes `airline`, `departTime` and
            `arriveTime` required on `FlightOption`, and a card without them
            does not compile. Not a binding either — that is what the renderer
            calls pending, and it shimmers for as long as the surface lives, so
            a hop knowing its number and price but not its airline drew two
            fields waiting for something nobody was going to send.

            An empty literal is the third thing, and the renderer already draws
            the distinction: "a literal is never pending — text written into
            the component by the model is as arrived as it will ever be."
            """
            return bind(model.binding_for(f"{prefix}{field}")) if has(field) else ""
        # A row per decision, and only once that decision is settled.
        #
        # These used to be drawn unconditionally, and the result was the
        # opposite of informative: before a fare was chosen the panel held a
        # `FlightOption` whose every field was bound to a key the trip had
        # not got, which the renderer draws — correctly — as a field waiting
        # for data. So a trip with nothing chosen showed two cards shimmering
        # for ever, and one with a fare chosen showed its price beside a
        # shimmering airline, because `/trip/airline` did not exist at all.
        #
        # A panel is a record of what has been settled. An empty row is not a
        # record of anything, and a row that waits for ever is a lie about a
        # search nobody is running.
        if hop.get("selectedFlight"):
            # One level deeper than the row being conditional, and for the same
            # reason: the agent reliably writes the outbound's airline and
            # times and reliably does not write the return's, however the brief
            # is worded. Two live runs and two rewrites of that rule later, the
            # panel is the thing to fix. See `shown`.
            rows.append(
                PanelFlight(
                    airline=shown("airline"),
                    departTime=shown("departTime"),
                    arriveTime=shown("arriveTime"),
                    origin=bind(model.binding_for(f"{prefix}origin")),
                    destination=bind(model.binding_for(f"{prefix}destination")),
                    price=bind(model.binding_for(f"{prefix}flightPrice")),
                    # The panel's one editable affordance: re-open a settled
                    # decision back in the conversation. `strip_panel_actions`
                    # keeps every other kind off a panel.
                    action={"event": {"name": "change", "context": {"what": "flight", "hop": index}}},
                    flightNumber=bind(model.binding_for(f"{prefix}selectedFlight")),
                    selected=bind(model.binding_for(f"{prefix}selectedFlight")),
                    accessibility=_reads(
                        "${/trip/" + prefix + "selectedFlight},",
                        "${/trip/" + prefix + "flightPrice}",
                    ),
                )
            )
        # Conditional on the *stay*, not on the nights. A hop that stays the
        # night but has no hotel yet is precisely the case that drew a card
        # waiting for a name that nothing was going to send.
        if hop.get("selectedHotel"):
            rows.append(
                StayRow(
                    # The name, not the id. `selectedHotel` is
                    # "h_BER_savigny", which is what the panel showed.
                    #
                    # And bound only if this hop has one, for the same reason
                    # as the fare's airline above: a card bound to a name
                    # nobody recorded waits for it for ever.
                    name=shown("hotelName"),
                    price=bind(model.binding_for(f"{prefix}nightlyPrice")),
                    action={
                        "event": {"name": "change", "context": {"what": "stay", "hop": index}}
                    },
                    selected=bind(model.binding_for(f"{prefix}selectedHotel")),
                    accessibility=_reads(
                        "${/trip/" + prefix + "hotelName},",
                        "${/trip/" + prefix + "nightlyPrice}",
                    ),
                )
            )

    return Column(children=rows)


# --------------------------------------------------------------------------
# The opening form
# --------------------------------------------------------------------------
#
# The biggest thing this agent writes, and it writes it on the slowest turn.
#
# Almost every conversation opens with the same surface: where you are flying
# from, the dates, how many are going — one set per hop, every control bound to
# the record, one button carrying every path. In Express that is thirty lines
# and the best part of a thousand tokens, composed before any lookup has run,
# which is why the opening turn is the slowest in the app: 22 to 35 seconds to
# a first interface, measured, against 8 or 9 for a turn that searches.
#
# `Ask()` is that surface. One section per hop of the route the trip has, with
# exactly the controls that hop still needs, and nothing for what is already
# settled — the agent asks for the gaps and never re-asks what it was told.


class Counter(ComponentBuilderNode):
    """How many are on this hop."""

    component: str = "TravelerCounter"
    label: Any = None
    value: Any = None
    min: Any = None
    max: Any = None
    caption: Any = None


class Dates(ComponentBuilderNode):
    """There and back, as one range."""

    component: str = "DateRangePicker"
    label: Any = None
    start: Any = None
    end: Any = None
    action: Any = None


class OneDate(ComponentBuilderNode):
    """A single hop's departure, where a range cannot say when it leaves."""

    component: str = "DateTimeInput"
    label: Any = None
    value: Any = None


class Choices(ComponentBuilderNode):
    """One of a known set — an airport this deployment actually flies."""

    component: str = "ChoicePicker"
    label: Any = None
    variant: Any = None
    options: Any = None
    value: Any = None
    filterable: Any = None


@macro
def ask(heading: str = "", label: str = "Find flights") -> Column:
    """Everything the trip still needs, as one surface with one button.

    The opening turn, and every turn that needs a gap filled: dates, who is
    going, where they are flying from, per hop, bound to the record and
    pre-filled from it. Only what is missing — a hop whose date is known gets
    no date control, and nothing already settled is asked again.

    Args:
        heading: The line at the top, e.g. 'Madrid in April — two travellers'.
        label: What the button says. Defaults to 'Find flights'.
    """
    from . import trip as model

    record = _TRIP.get()
    record = record if isinstance(record, dict) else {}
    rows: list[Any] = []
    edits: list[str] = []
    if isinstance(heading, str) and heading.strip():
        rows.append(Text(text=heading, variant="h3"))

    hops = model.journey(record)
    # A range picker is for there and back and nothing else: it cannot say when
    # the middle hop of a three-city route leaves, which is how a four-hop trip
    # ended up with two dates and no way to express the rest. A trip with no
    # explicit legs is the there-and-back shape.
    there_and_back = not record.get("legs")

    # Where they are going, and where from.
    #
    # These were missing outright. The docstring claimed "where they are flying
    # from" and the brief told the agent to draw "a ChoicePicker of airports for
    # anything you cannot place", and this macro drew dates and counters and
    # nothing else — so once `Ask()` became *the* opening surface, the one
    # control a traveller needs on the one turn where nothing is known
    # disappeared. They could say Berlin out loud and had nowhere to say
    # Copenhagen.
    #
    # A picker rather than a text field because an airport typed wrong is a
    # lookup that finds nothing, and this deployment knows exactly which ones
    # it flies. `mutuallyExclusive`, so the renderer writes the code itself
    # rather than a list of one.
    airports = _AIRPORTS.get() or {}
    for key, choices, label in (
        ("destination", airports.get("to") or [], "Where to"),
        ("origin", airports.get("from") or [], "Flying from"),
    ):
        if record.get(key) or not choices:
            continue
        path = model.binding_for(key)
        rows.append(
            Choices(
                label=label,
                variant="mutuallyExclusive",
                options=choices,
                value=bind(path),
                filterable=len(choices) > 8,
            )
        )
        edits.append(path)

    # Dates. One range for there and back, one input per hop otherwise — a
    # range cannot say when the middle hop of a three-city route leaves, which
    # is how a four-hop trip ended up with two dates.
    if there_and_back and not (record.get("startDate") and record.get("endDate")):
        rows.append(
            Dates(
                label="Travel dates",
                start=bind(model.binding_for("startDate")),
                end=bind(model.binding_for("endDate")),
                action={"event": {"name": "dates_changed", "context": {}}},
            )
        )
        edits += [model.binding_for("startDate"), model.binding_for("endDate")]
    else:
        for hop in hops:
            index = hop.get("hop") or 0
            prefix = "" if index == 0 else f"legs/{index - 1}/"
            if hop.get("startDate"):
                continue
            rows.append(
                OneDate(
                    label=f"Leaving {hop.get('from') or 'home'}",
                    value=bind(model.binding_for(f"{prefix}startDate")),
                )
            )
            edits.append(model.binding_for(f"{prefix}startDate"))

    # Who is on each hop. One counter per hop, labelled by hop, because the
    # party is a property of the hop — "my partner joins me in Chicago" is a
    # sentence one counter cannot hold.
    for hop in hops:
        index = hop.get("hop") or 0
        prefix = "" if index == 0 else f"legs/{index - 1}/"
        path = model.binding_for(f"{prefix}travelers")
        rows.append(
            Counter(
                label=f"Travelling {hop.get('from') or ''} → {hop.get('to') or ''}".strip(),
                value=bind(path),
                min=1,
                max=8,
            )
        )
        edits.append(path)

    # One button, carrying every path above. A surface whose values never reach
    # the trip is a form nobody can submit.
    # The SDK's own `Button`, not a node of this file's own: `child` is a
    # component *id* on the wire, and the builder's annotated field is what
    # hoists the inline `Text` out and leaves the reference behind. Declaring it
    # here as a plain field produced a button whose child was an object, which
    # the catalog rejects — caught by the check that compiles every example in
    # these prompts.
    rows.append(
        Button(
            child=Text(text=label or "Find flights"),
            variant="primary",
            action=Action(event=ActionEvent(name="commit_surface", context={"paths": edits})),
        )
    )
    return Column(children=rows, align="stretch")


#: Every macro this catalog advertises.
MACROS = (itinerary, flights, stays, highlights, trip, ask)

#: One expander, built once: the schemas it synthesises do not depend on the
#: trip, only the expansion does — which is why the prompt can be cached and
#: still be true.
EXPANDER = MacroExpander(list(MACROS))


def with_macros(catalog: Any) -> Any:
    """The catalog as the *model* sees it: components plus macros."""
    return EXPANDER.transform_to_inference_catalog(catalog)


def expand(
    messages: Any,
    trip: dict[str, Any] | None = None,
    airports: dict[str, list[dict[str, str]]] | None = None,
) -> Any:
    """The same messages with every macro replaced by what it stands for.

    Runs on the way out, after compiling and before any pass that reads
    components — so the checks, the commit binder and the renderer all see the
    real tree and none of them needs to know macros exist.

    The trip is passed rather than ambient. It was a context variable first,
    which reads better and is wrong here: a turn is an async generator, and the
    context a generator resumes in is the caller's, not the one it was started
    in. A macro would have expanded against whatever trip the *client's* last
    `__anext__` happened to carry.

    Takes and returns whatever the compiler handed over — typed models, as of
    agent-sdk 0.9 — rather than the plain dicts the rest of this app passes
    around, because the expander reads the models. So this runs *before*
    `as_wire`, not after it, and the messages are untouched when no macro is in
    them, which is most surfaces and every surface the host composes itself.
    """
    if not any(_holds_a_macro(_as_dict(message)) for message in messages):
        return messages
    with for_trip(trip or {}, airports):
        return EXPANDER.transform_to_transport(list(messages))


def _holds_a_macro(message: Any) -> bool:
    from .wire import components_of

    names = {str(node.get("component") or "") for node in components_of(message)}
    return any(meta.name in names for meta in EXPANDER.macros)


def _as_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    return message.model_dump(exclude_none=True, by_alias=True)


def panel_redraw(trip: dict[str, Any], surface_id: str, version: str) -> list[dict[str, Any]]:
    """`Trip()` expanded against this trip, as messages for a standing panel.

    No model call: this compiles nine characters of Express the panel is
    already made of and expands the macro against the record. Microseconds.

    It exists because rows became conditional. `Trip()` draws a fare row only
    once a fare is chosen, which is what a panel is for — a record of what is
    settled, not a row shimmering at a decision nobody has made. But a row that
    was not there is a *component*, and `updateDataModel` cannot add one. So
    the first appearance of each row waited for the panel to be redrawn, and
    the only thing that redrew it was the client asking after the answering
    turn had finished: measured at 9.7s after a fare was pressed and 59.4s
    after a stay, because the turn that answers a stay is the itinerary.

    This is not the host deciding what the panel holds. `PANEL_REQUEST` asks
    the agent for `Trip()`, the agent draws `Trip()`, and this re-expands that
    same macro when the record moves under it. What it replaces is a model turn
    that produced the identical surface.
    """
    from .catalog import parser_for
    from .express import as_wire

    source = "\n".join(
        [f"surface({json.dumps(surface_id, ensure_ascii=False)})", "panel = Trip()", "root = Column([panel])"]
    )
    try:
        drawn = as_wire(expand(parser_for(surface_id).compile(source, is_final=True), trip))
    except Exception:  # noqa: BLE001 - a panel is never worth a failed turn
        return []
    for message in drawn:
        if isinstance(message, dict):
            message.setdefault("version", version)
    return list(drawn)
