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
import re
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
#: Here rather than passed as a macro argument because `AirportPicker.options`
#: is a static array in the schema — not a `DynamicStringList` — so the choices
#: have to exist when the macro expands, not when the surface renders. And the
#: agent cannot supply them: it would have to call a tool to find out what this
#: provider flies, on the one turn where it already has the least to go on.
#:
#: Shape: `{"from": [{"value": "CPH", "label": "Copenhagen", "code": "CPH",
#: "detail": "Europe"}, …], "to": […]}`
_AIRPORTS: contextvars.ContextVar[dict[str, list[dict[str, str]]]] = contextvars.ContextVar(
    "airports", default={}
)


def heading_text(text: str, level: int = 3) -> Text:
    """A heading, written the way A2UI 1.0 writes one: as Markdown in a `Text`.

    1.0's basic `Text` has two variants, `caption` and `body`; `h1`…`h5` were
    0.9's. Headings drawn as `variant="h3"` were rejected by `@a2ui/web_core`
    and passed only our own validator, which read a stale copy of the basic
    catalog. The heading level is the Markdown's, so it still renders as one.
    """
    return Text(text=f"{'#' * level} {text.lstrip('#').strip()}")


#: The ISO code this turn's money is quoted in. See `currency_for`.
#:
#: Here for the same reason the airports are: `formatCurrency` takes the code
#: as an argument, and a macro expanding against the record has to know it when
#: it writes the call, not when the surface renders.
_CURRENCY: contextvars.ContextVar[str] = contextvars.ContextVar("currency", default="USD")


class for_trip:
    """Expand this turn's macros against this trip, and this deployment's airports."""

    def __init__(
        self,
        trip: dict[str, Any],
        airports: dict[str, list[dict[str, str]]] | None = None,
        currency: str | None = None,
    ) -> None:
        # The dict itself, not a copy: a turn mutates its trip in place as
        # tools run, and a macro has to see the `days` that `save_trip` wrote
        # a moment ago rather than the trip as it was when the turn began.
        self._trip = trip if isinstance(trip, dict) else {}
        self._airports = airports if isinstance(airports, dict) else {}
        self._currency = str(currency or "USD")
        self._tokens: list[Any] = []

    def __enter__(self) -> "for_trip":
        self._tokens = [
            _TRIP.set(self._trip),
            _AIRPORTS.set(self._airports),
            _CURRENCY.set(self._currency),
        ]
        return self

    def __exit__(self, *_: Any) -> None:
        for var, token in zip((_TRIP, _AIRPORTS, _CURRENCY), self._tokens):
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
        rows.append(heading_text(heading))

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


def chosen(path: str) -> dict[str, Any]:
    """Whether the row being drawn is the one recorded at `path`.

    `selected` is a boolean and the trip records an id, so binding one to the
    other gave every row the chosen id: a string, which no renderer reads as
    `true`, and the fare you picked was never marked on the list. The catalog's
    `equals` compares them per row, against the row's own `id`.
    """
    return {"@call": "equals", "args": {"a": bind("id"), "b": bind(path)}}


def _reads(*fields: str) -> dict[str, Any]:
    """A label that reads the row aloud as a sentence.

    `formatString` resolves against the row being drawn, so one component names
    however many rows arrive. A card read in field order is "Iberia IB6250
    18:40 JFK 08:15 +1 MAD 7h 35m Nonstop $412" — every fact and no sentence —
    and `accessibility.label` replaces that rather than adding to it.
    """
    return {"label": {"@call": "formatString", "args": {"value": " ".join(fields)}}}


def _said(*fields: str) -> dict[str, Any]:
    """What a press says in the conversation, as A2UI's `event.userMessage`.

    Resolved against the row pressed, so the transcript reads "Chose TAP Air
    Portugal TP787, 11:00 → 21:44, €292" rather than the context's keys.
    """
    return {"@call": "formatString", "args": {"value": " ".join(fields)}}


def _hop_in(path: Any) -> Optional[int]:
    """The hop a `selected` path is talking about, if it names a leg.

    `Flights(…, selected="/trip/legs/0/selectedFlight")` is a list of fares for
    hop two whether or not the agent also passed `hop=2`, and measured, it
    passes the path and omits the number: a whole browser walkthrough recorded
    `"hop": 2` zero times while binding `selected` to a leg every time.

    Without the hop the press lands with nothing saying which leg it settled,
    so the sentence that tells the agent where to put the airline and the times
    never fires — and the fix for that was correct and simply unreached.
    """
    found = re.search(r"/legs/(\d+)/", str(path or ""))
    return int(found.group(1)) + 2 if found else None


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


def _money(path: str) -> dict[str, Any]:
    """A stored amount, drawn with its currency.

    `flightPrice` and `nightlyPrice` are `money` fields and the trip keeps them
    as numbers, because a total is arithmetic. Bound straight into a card they
    therefore render as `69`, while the fare list beside them says `€69` —
    the provider quotes a display string and the record keeps a number.

    `formatCurrency` is in the catalog and the renderer implements it, so the
    panel formats the number it has rather than the app storing a second,
    pre-formatted copy of it that something has to keep in step.
    """
    return {
        "@call": "formatCurrency",
        # Whole units, as a fare is quoted: the SDK's default is two places,
        # which drew `$292.00` beside a fare list saying `€292`.
        "args": {"value": bind(path), "currency": _CURRENCY.get(), "decimals": 0},
    }


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
    hop = _hop(hop) or _hop_in(selected)
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
                "userMessage": _said(
                    "Chose ${airline} ${flightNumber},", "${departTime} → ${arriveTime}, ${price}"
                ),
                "context": _context(
                    hop,
                    id=bind("id"),
                    price=bind("price"),
                    # The airports it flies between, so the host can tell
                    # which hop was pressed without trusting `hop`. Not
                    # `origin` and `destination`: those are the trip's own
                    # fields, and a return fare would overwrite the route.
                    **{"from": bind("origin"), "to": bind("destination")},
                    airline=bind("airline"),
                    flightNumber=bind("flightNumber"),
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
        selected=chosen(selected) if selected else None,
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
        rows.append(heading_text(heading))
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
    hop = _hop(hop) or _hop_in(selected)
    row = StayRow(
        name=bind("name"),
        price=bind("price"),
        action={
            "event": {
                # This one already carried the name; what it lacked was a place
                # on the trip to put it. See `hotelName` in `trip-model.json`.
                "name": "select_hotel",
                "userMessage": _said("Chose ${name}, ${price}"),
                "context": _context(
                    hop, id=bind("id"), name=bind("name"), price=bind("price")
                ),
            }
        },
        neighborhood=bind("neighborhood"),
        rating=bind("rating"),
        amenities=bind("amenities"),
        badge=bind("badge"),
        selected=chosen(selected) if selected else None,
        accessibility=_reads("${name}, ${neighborhood},", "rated ${rating}, ${price}"),
    )
    rows: list[Any] = []
    if isinstance(heading, str) and heading.strip():
        rows.append(heading_text(heading))
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
        rows.append(heading_text(heading))
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
        # The panel, when a decision has just given it a row it did not have.
        #
        # `Trip()` draws a fare row only once a fare is chosen, and a row that
        # was not there is a component — `updateDataModel` cannot add one. So
        # the first appearance of each row needs the panel drawn again.
        #
        # The host used to do that on its own whenever `decision_shape` moved.
        # It worked and it was the wrong shape: every other surface in this app
        # goes up because the agent asked for it, and that one went up because
        # the host decided the panel was stale. Asking costs the agent four
        # words in a call it was already making.
        "Trip": ("heading", "money"),
    },
}

#: Where a macro draws, when it is not the card this turn is answering.
#:
#: `Trip()` is the standing panel and belongs on the panel's surface however it
#: was asked for — the agent naming it in `save_trip` should not put a sidebar
#: on an inline card.
DRAWS_ONTO = {"Trip": "sidebar"}


def currency_for(destinations: Sequence[dict[str, Any]], trip: dict[str, Any]) -> str:
    """The code this trip's money is quoted in, for `formatCurrency`.

    Read off the destinations the door already fetched for `Ask()`'s pickers,
    so the panel costs no extra call to say "€69" instead of "69".

    The *trip's* destination and not the hop's, which is the subtlety
    `_trip_currency` documents in `tools/answers.py`: pricing the way home
    means calling `search_flights` with `destination: "CPH"`, and a currency
    read off that comes back as kroner for the return of a Berlin trip whose
    outbound and hotel are both in euros. Dollars when nothing is settled,
    which is what every caller got before any of this existed.
    """
    where = str((trip or {}).get("destination") or "").strip().casefold()
    if not where:
        return "USD"
    for entry in destinations or ():
        if not isinstance(entry, dict):
            continue
        names = {
            str(entry.get("city") or "").casefold(),
            str(entry.get("airport") or "").casefold(),
        }
        if where in names and entry.get("currency"):
            return str(entry["currency"])
    return "USD"


def airport_choices(
    origins: Sequence[dict[str, Any]], destinations: Sequence[dict[str, Any]]
) -> dict[str, list[dict[str, str]]]:
    """The provider's two lists, as `AirportPicker` options for `Ask()`.

    Pure, and takes the lists rather than the provider, so the awaiting happens
    once in the door and this stays testable without one.

    Each option names the city, the code and a second line (the country for a
    destination, the region for an origin), because a traveller searches by
    city and may not know the code. What each one *stores* differs, and follows
    the field rather than the control: `origin` is "three-letter code", so the
    option stores CPH; `destination` is "city or airport", and the city is what
    the panel heading, the prose and every later lookup read better — a trip
    stored as "→ MAD" says MAD everywhere a person expects Madrid.
    """

    def option(value: str, city: str, code: str, detail: Any) -> dict[str, str]:
        made = {"value": value, "label": city or code}
        if code:
            made["code"] = code
        said = str(detail or "").strip()
        if said.islower():  # a slug, "north-america", rather than a name
            said = " ".join(word.capitalize() for word in said.split("-") if word)
        if said:
            made["detail"] = said
        return made

    out: dict[str, list[dict[str, str]]] = {"from": [], "to": []}
    for entry in origins or ():
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip()
        if code:
            city = str(entry.get("city") or "").strip()
            out["from"].append(option(code, city, code, entry.get("region")))
    for entry in destinations or ():
        if not isinstance(entry, dict):
            continue
        city = str(entry.get("city") or "").strip()
        code = str(entry.get("airport") or "").strip()
        if city or code:
            out["to"].append(option(city or code, city, code, entry.get("country")))
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
    # A macro with a home of its own goes there. See `DRAWS_ONTO`.
    surface_id = DRAWS_ONTO.get(macro, surface_id)
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
        if key == "money":
            # A flag, not a string. `quoted(False)` is `""`, which the trailing
            # trim below then drops — so asking for the total would have
            # compiled to a macro call that never mentioned it.
            args.append("true" if value is True else "false")
            continue
        args.append(quoted(value))
    # Trailing empties only repeat the macro's own defaults. Dropping them from
    # the end — never the middle — keeps `Flights("", "/trip/selectedOutbound")`
    # addressing `selected` by position while `Highlights()` stays nine
    # characters, which is the whole reason a turn will spend them.
    while args and args[-1] in ('""', "false"):
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


#: An `<a2ui>` block's contents, and the surface a block addresses.
_BLOCK = re.compile(r"<a2ui>\s*(.*?)\s*</a2ui>", re.DOTALL)
_ADDRESSED = re.compile(r'^\s*surface\(\s*["\']([^"\']+)["\']\s*\)', re.MULTILINE)


def panel_composition(said: str, standing: Sequence[str]) -> dict[str, str]:
    """The Express the agent wrote for each standing surface, by surface.

    Kept so that a later change to the record is a *re-render* rather than
    another model turn. The composition is the agent's — `panel = Trip("Your
    trip to Madrid")`, in its own words, addressed to the panel by name — and
    re-compiling it against a trip that has moved is the same interface drawn
    from newer facts, not a new interface the host decided on.

    The source and not the compiled messages, which is the whole point: the
    messages are a snapshot of the record at the moment the block was written,
    and a snapshot is the thing that goes stale.

    Why this is needed at all: a panel's rows are conditional, so a row's first
    appearance is a component and bound data cannot add one. The agent is asked
    to redraw — a hint in the turn's notes, `Trip` offered on `save_trip`'s
    `draw`, the brief saying to write the block first — and measured over a full
    walk it did so zero times. The composition is still its own; only the clock
    stops depending on it.
    """
    found: dict[str, str] = {}
    for block in _BLOCK.findall(said or ""):
        addressed = _ADDRESSED.search(block)
        if addressed and addressed.group(1) in standing:
            found[addressed.group(1)] = block.strip()
    return found


def composition_for(said: str, surface_id: str) -> str:
    """The Express a panel model wrote for one standing surface, addressed to it.

    `panel_composition`, for a draw that was asked for one surface and so knows
    which: a block that did not name its surface is still that surface's, and
    is kept addressed to it so a replay lands on the panel.
    """
    blocks = _BLOCK.findall(said or "")
    if not blocks:
        return ""
    source = blocks[-1].strip()
    if not _ADDRESSED.search(source):
        source = f'surface("{surface_id}")\n{source}'
    return source


def replay(source: str, trip: dict[str, Any], surface_id: str, version: str) -> list[dict[str, Any]]:
    """One stored composition, re-rendered against the trip as it stands.

    No model call: this compiles Express the agent already wrote and expands the
    macros in it against the record. Microseconds, against the four to six
    seconds a model takes to answer with the block it has given us once already.
    """
    if not source:
        return []
    from .catalog import parser_for
    from .express import as_wire

    try:
        drawn = as_wire(
            expand(
                parser_for(surface_id).compile(source, is_final=True),
                trip,
                currency=str(trip.get("currency") or "USD"),
            )
        )
    except Exception:  # noqa: BLE001 - a stale panel is never worth a failed turn
        return []
    for message in drawn:
        if isinstance(message, dict):
            message.setdefault("version", version)
    return list(drawn)


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


#: The lookups whose rows the agent *composes* with, rather than points a macro at.
#:
#: `get_destination` is the one. Its rows are what a day plan is made out of: the
#: agent reads the Prado and writes it into a morning, so taking them away would
#: take away the material. A fare is chosen, never composed — nobody writes a
#: flight — which is the whole difference, and the reason this is a list of one
#: rather than a judgement call per tool.
COMPOSED_FROM = {"get_destination"}


#: Lookups whose rows the model is not handed, and the key they arrive under.
#:
#: Derived, not declared. The rule is "what the host files, the agent does not
#: need": the rows land in the data model and a macro reads them, so `Flights()`
#: is nine characters bound to `/flights`, a press hands back the chosen row's
#: own fields, and the catalog already forbids writing a fare card per result.
#: Handing the table over as well buys nothing and costs 46% of a flights result
#: and 52% of a stay's, carried for the rest of the conversation.
#:
#: Derived *because* the bug this replaces was two tables disagreeing. The voice
#: door kept its own copy that looked for `result["items"]`, a key no tool here
#: has ever returned, so it withheld nothing for as long as it existed. A
#: spelling cannot drift from itself.
WITHHELD: dict[str, str] = {
    tool: rows_key for tool, (_, rows_key) in LANDINGS.items() if tool not in COMPOSED_FROM
}


def without_the_rows(tool: str, result: Any, reads_them: str) -> Any:
    """A lookup's answer with the table taken out and a summary left behind.

    What replaces the rows is what the agent actually reasons with: how many
    there are, what they cost at each end, and which is cheapest — enough to
    say "four fares, €298 to €512" or to answer "is there a nonstop", and not
    enough to recite. Everything that was never a row — the provenance, the
    per-party wording, what was searched for — is kept untouched.

    `reads_them` is the one sentence that differs per channel: on a text door
    the macro reads them off the path, on the spoken door a `show_*` tool puts
    them on screen. That is the only thing about this a channel gets to decide,
    which is why it is an argument rather than two copies of the function.

    This is not composition moving to the server. The agent still chooses the
    tool, the surface, the heading and where the choice is recorded. It just
    cannot narrate a table it was never handed — which is the bug this exists
    for, measured on the spoken door as four fares read down a phone line and a
    closing "you can see the options here" with nothing on screen at all.

    Keyed off `WITHHELD`, which names the same row key `LANDINGS` files from.
    The previous attempt at this lived on the voice door and read
    `result["items"]`, a key no tool here has ever returned, so it passed every
    result through untouched for as long as it existed. One table, next to the
    filing it mirrors, is how that stops being possible.
    """
    key = WITHHELD.get(tool)
    if not key or not isinstance(result, dict):
        return result
    rows = result.get(key)
    if not isinstance(rows, list) or not rows:
        return result

    priced = [
        row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("priceValue"), (int, float))
    ]
    kept = {name: value for name, value in result.items() if name != key}
    kept["found"] = len(rows)
    if priced:
        cheapest = min(priced, key=lambda row: row["priceValue"])
        dearest = max(priced, key=lambda row: row["priceValue"])
        kept["cheapest"] = cheapest.get("price")
        kept["dearest"] = dearest.get("price")
        # Named, because "the cheapest is €298" is a figure and "the cheapest is
        # TAP, one stop via Lisbon" is an answer. One row's worth of detail is
        # affordable; the table is not.
        named = cheapest.get("name") or " ".join(
            str(cheapest.get(field) or "").strip()
            for field in ("airline", "flightNumber")
        )
        if named.strip():
            kept["cheapestIs"] = named.strip()
    kept["rowsAre"] = (
        f"The {len(rows)} results are not in this response, on purpose: a list in "
        f"context is a list read out, and nothing here needs to read them. {reads_them} "
        "Say one sentence about what is on screen."
    )
    return kept




# `seed_rows` and `clear_rows` are gone.
#
# They filed three blank rows at a lookup's landing path at dispatch, and took
# them away again if the lookup found nothing. The point was the shimmer: a
# template over an empty array draws nothing, so a pre-drawn list was blank
# space until the rows arrived, and three rows of unresolved paths let the
# renderer's own pending rule fill the wait.
#
# Data rather than components, so it composed nothing — but it was still the
# host inventing rows no lookup had returned and no agent had asked for, and
# choosing how many. `file_rows` below is the host's actual share of a search:
# what the lookup found, at its address.
#
# The shimmer came back, asked for rather than assumed: see `placeholder_rows`.


def placeholder_rows(
    tool: str, count: Any, surface_id: str, version: str
) -> list[dict[str, Any]]:
    """Blank rows at a lookup's landing path, as many as the agent asked for.

    The shimmer, restored the right way round. `seed_rows` used to file three
    of these at every lookup whether anybody wanted them or not — the host
    inventing rows no lookup had returned, and picking the number. This files
    what `draw: {placeholders: n}` asked for and nothing otherwise, so the
    decision is the agent's and the arithmetic is ours.

    A blank row is `{}`, which matters: every bound field on the template then
    fails to resolve, and the renderer's own rule turns that into the pending
    state — "a path that does not resolve is pending, a path that resolves to
    an empty string is empty". Rows of empty strings would paint as fares with
    no airline and no price, which reads as an answer and is worse than a wait.

    Capped, because this is a number a model wrote: a template asked to draw
    two hundred pending rows is a frozen tab, and the shape of a list is
    legible at three.
    """
    path = landing_for(tool)
    if path is None or not isinstance(count, int) or isinstance(count, bool) or count < 1:
        return []
    return [
        {
            "version": version,
            "updateDataModel": {
                "surfaceId": surface_id,
                "path": path,
                "value": [{} for _ in range(min(count, 8))],
            },
        }
    ]


def clear_placeholders(tool: str, surface_id: str, version: str) -> list[dict[str, Any]]:
    """Take them away, for a lookup that came back with nothing.

    The one case where filing `[]` is right. Everywhere else it would blank a
    card the traveller is reading, which is why `rows_in` answers `None`
    rather than `[]` for a refusal — but rows that went up seconds ago on the
    promise of a result nobody is reading, and leaving them pending for ever
    says "still looking" about a search that is over.
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


class Stat(ComponentBuilderNode):
    """One figure on the panel, bound rather than written.

    `label`, `value` and `caption` are all `DynamicString` in the catalog, so a
    binding is as valid as a string — and has to be, because the figures this
    draws move whenever a decision does.
    """

    component: str = "StatTile"
    label: Any = None
    value: Any = None
    caption: Any = None
    accessibility: Any = None


class BoundText(ComponentBuilderNode):
    """A `Text` whose content may be a function call, not only a string.

    The builder's own `Text` validates `text` against the 0.9 models, where a
    `FunctionCall` serialises as `call`. The renderer reads 1.0, where it is
    `@call` — so the strict path rejects the right spelling and accepts a
    spelling that compiles and then draws nothing at all, which is the worse of
    the two failures.

    So this takes `Any` and the raw dict goes through untouched, exactly as
    `_money` already does for a price. See `PanelFlight`, which is permissive
    for the same reason.
    """

    component: str = "Text"
    text: Any = None
    variant: Any = None


@macro
def trip(heading: str = "", money: Any = False) -> Column:
    """The trip as it stands, as the standing panel draws it.

    One section per hop of the route the trip currently has, every value bound
    to the record so that what the traveller settles next arrives without
    another turn. Write it on the panel — `surface("sidebar")` — and nothing
    needs to redraw it again.

    Args:
        heading: Optional line at the top, e.g. 'Your trip to Madrid'.
        money: Whether to show what has been committed and what is left of the
            budget. Off by default — a panel saying "Total 0" is a claim about
            a trip nobody has priced — and worth asking for the moment a fare
            or a nightly rate is chosen.
    """
    from . import trip as model

    record = _TRIP.get()
    rows: list[Any] = []
    if isinstance(heading, str) and heading.strip():
        rows.append(heading_text(heading))

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
        rows.append(heading_text(where.strip(" →"), level=4))


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

        # When this hop goes, and who is on it.
        #
        # The panel drew the route, the fare and the stay, and never these —
        # so a hop whose dates and party were settled turns ago showed nothing
        # about either, and "the right side does not show dates and travellers
        # for each leg when confirmed" is exactly right.
        #
        # Bound, not written out, so the line follows the record: change the
        # party on hop two and the panel moves without anybody redrawing it.
        # And only the parts this hop has — the same rule as the rows below,
        # for the same reason. A hop that knows when it goes and not yet who is
        # on it says when it goes.
        said: list[str] = []
        # Dates through `formatDate`, so the line reads "12 Apr – 19 Apr"
        # rather than the record's ISO strings.
        def day(field: str) -> str:
            return "${formatDate(value: ${/trip/" + prefix + field + "}, format: 'd MMM')}"

        if has("startDate"):
            said.append(day("startDate"))
            if has("endDate"):
                said.append("– " + day("endDate"))
        if has("travelers"):
            said.append(("· " if said else "") + "${/trip/" + prefix + "travelers} travelling")
        if said:
            rows.append(
                BoundText(
                    text={"@call": "formatString", "args": {"value": " ".join(said)}},
                    variant="caption",
                )
            )
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
            number = "flightNumber" if has("flightNumber") else "selectedFlight"
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
                    price=_money(model.binding_for(f"{prefix}flightPrice")),
                    # The panel's one editable affordance: re-open a settled
                    # decision back in the conversation. `strip_panel_actions`
                    # keeps every other kind off a panel.
                    action={"event": {"name": "change", "context": {"what": "flight", "hop": index}}},
                    # The number off the card when the hop has it. It used to be
                    # the fare's id, which is a flight number only where a
                    # provider happens to use one as its id — the sample trip
                    # showed TP2077 beside a card that said TP787.
                    flightNumber=bind(model.binding_for(f"{prefix}{number}")),
                    # The panel draws this row only once a fare is chosen.
                    selected=True,
                    accessibility=_reads(
                        "${/trip/" + prefix + number + "},",
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
                    price=_money(model.binding_for(f"{prefix}nightlyPrice")),
                    action={
                        "event": {"name": "change", "context": {"what": "stay", "hop": index}}
                    },
                    selected=True,
                    accessibility=_reads(
                        "${/trip/" + prefix + "hotelName},",
                        "${/trip/" + prefix + "nightlyPrice}",
                    ),
                )
            )

    # What it comes to, and what is left of the budget — when asked for.
    #
    # These three tiles were built here unconditionally once, which was the
    # host deciding that a budget line belongs on the panel off a request that
    # was only "show a running total". Taking them out went too far the other
    # way: the panel is usually drawn as `draw: {macro: "Trip"}`, where the
    # macro call *is* the whole block, so an agent that wanted a total had
    # nowhere to put one and the figures went nowhere. Removing the host's
    # opinion removed the feature.
    #
    # `money` is the opinion, handed back: the arithmetic and the currency are
    # the host's — `money_rows` files them at `/money` every turn, bound, so
    # they move as decisions land without a redraw — and whether this panel
    # shows them is the agent's, in one word, on a call it is already making.
    #
    # Bound through `formatCurrency`, because the record keeps a number: a
    # total read straight out of `/money/total` draws as `584` beside a fare
    # list that says `€292`.
    if money not in (False, None, "", "false", "no", 0):
        from .finishing import money_rows

        figures = money_rows(record) if isinstance(record, dict) else {}
        if figures.get("total") is not None:
            rows.append(Stat(label="Committed so far", value=_money("/money/total")))
        if figures.get("budget") is not None:
            rows.append(Stat(label="Budget", value=_money("/money/budget")))
        if figures.get("remaining") is not None:
            rows.append(
                Stat(
                    # Named for what the number means, which flips with its sign.
                    label="Over budget by" if figures.get("over") else "Left to spend",
                    value=_money("/money/remaining"),
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


class Place(ComponentBuilderNode):
    """Where from or where to: a place this deployment actually flies."""

    component: str = "AirportPicker"
    label: Any = None
    value: Any = None
    options: Any = None
    kind: Any = None
    placeholder: Any = None


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

    def settled(key: str) -> bool:
        """Whether this field has an answer, as opposed to merely a value.

        A field the agent *assumed* has a value and is not settled, and this is
        the difference between the two. "I want to go to Madrid in April with my
        partner" names no dates, so the agent picks a plausible week, records it
        as `assumed` — which is right, it is a starting point — and the form then
        tested `record.get("startDate")`, found April 11th, and drew no date
        control. The turn's own sentence said "let's set your exact April dates".
        There was nowhere to set them.

        So the picker is drawn, bound to the path the assumption is already in,
        which is better than either half: they see the week the agent chose and
        change it or press the button. Showing what was understood, and asking
        about only the part that was guessed.
        """
        value = record.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            return False
        return key not in (record.get("assumed") or [])

    rows: list[Any] = []
    if isinstance(heading, str) and heading.strip():
        rows.append(heading_text(heading))

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
    # A search field with a type-ahead list rather than a text box, because an
    # airport typed wrong is a lookup that finds nothing and this deployment
    # knows exactly which ones it flies; and rather than a `ChoicePicker`,
    # because that is a column of radio buttons, twenty-one deep for "Where
    # from?".
    airports = _AIRPORTS.get() or {}
    # `asks`, not `label`: this loop used to bind its own `label` and so
    # shadowed the *button's* label, which is a parameter of this function. The
    # loop left it holding "Flying from" — the last entry below — and the submit
    # button at the bottom of the form rendered that instead of "Find flights".
    # Only when a picker was drawn at all, which is most opening turns.
    # From before to, the order every flight search asks them in.
    for key, choices, asks, kind in (
        ("origin", airports.get("from") or [], "Where from?", "origin"),
        ("destination", airports.get("to") or [], "Where to?", "destination"),
    ):
        if settled(key) or not choices:
            continue
        path = model.binding_for(key)
        rows.append(
            Place(
                label=asks,
                value=bind(path),
                options=choices,
                kind=kind,
                placeholder="City or airport",
            )
        )

    # Dates. One range for there and back, one input per hop otherwise — a
    # range cannot say when the middle hop of a three-city route leaves, which
    # is how a four-hop trip ended up with two dates.
    if there_and_back and not (settled("startDate") and settled("endDate")):
        rows.append(
            Dates(
                label="Travel dates",
                start=bind(model.binding_for("startDate")),
                end=bind(model.binding_for("endDate")),
                action={"event": {"name": "dates_changed", "context": {}}},
            )
        )
    else:
        for hop in hops:
            index = hop.get("hop") or 0
            prefix = "" if index == 0 else f"legs/{index - 1}/"
            # Hop one's date is the trip's own field, so an assumption on it is
            # the trip's assumption. A later hop keeps its date on its leg,
            # where `assumed` does not reach — those are asked about whenever
            # they are blank, which is the same test either way.
            if settled("startDate") if index == 0 else hop.get("startDate"):
                continue
            rows.append(
                OneDate(
                    label=f"Leaving {hop.get('from') or 'home'}",
                    value=bind(model.binding_for(f"{prefix}startDate")),
                )
            )

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

    # One button. A surface whose values never reach the trip is a form nobody
    # can submit; the values themselves travel as the surface's data model.
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
            # Every value on the surface travels with the press as its data
            # model (`sendDataModel`), so the button need not list them.
            action=Action(event=ActionEvent(name="commit_surface", context={})),
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
    currency: str | None = None,
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
    with for_trip(trip or {}, airports, currency):
        return EXPANDER.transform_to_transport(list(messages))


def _holds_a_macro(message: Any) -> bool:
    from .wire import components_of

    names = {str(node.get("component") or "") for node in components_of(message)}
    return any(meta.name in names for meta in EXPANDER.macros)


def _as_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    return message.model_dump(exclude_none=True, by_alias=True)

