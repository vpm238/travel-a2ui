"""Macros: one-line components the model writes and the host expands.

A macro is a component in the model's catalog that no renderer sees. The model
writes `Flights("Outbound · JFK → MAD")`; before the surface goes out, the A2UI
SDK's `MacroExpander` replaces it with the components it stands for.

Every macro here is a pure template. What it expands into depends on its
arguments and nothing else; the content arrives as data, bound by path, from
the roots the host publishes (`brain/data.py`). So the model knows exactly what
a macro draws, the same call always draws the same tree, and a panel stays
current through `updateDataModel` with no redraw.

The model decides whether a macro appears, where, beside what and under which
heading. The macro saves it re-typing rows a lookup has already returned.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from a2ui.builder.v1_0 import (
    ChildList,
    Column,
    ComponentBuilderNode,
    DataBinding,
    DynamicChildList,
    Text,
)
from a2ui.builder.v1_0 import (
    List as ListOf,
)
from a2ui.transformers import MacroExpander, macro

# --------------------------------------------------------------------------
# The travel components a macro emits
# --------------------------------------------------------------------------


class FlightOption(ComponentBuilderNode):
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
    total: Any = None
    badge: Any = None
    selected: Any = None
    accessibility: Any = None


class HotelCard(ComponentBuilderNode):
    component: str = "HotelCard"
    name: Any = None
    price: Any = None
    action: Any = None
    neighborhood: Any = None
    rating: Any = None
    amenities: Any = None
    badge: Any = None
    selected: Any = None
    accessibility: Any = None


class ActivityItem(ComponentBuilderNode):
    component: str = "ActivityItem"
    title: Any = None
    time: Any = None
    category: Any = None
    location: Any = None
    duration: Any = None
    note: Any = None
    done: Any = None
    action: Any = None
    onRemove: Any = None
    accessibility: Any = None


class ItineraryDay(ComponentBuilderNode):
    component: str = "ItineraryDay"
    title: Any = None
    date: Any = None
    summary: Any = None
    children: Optional[ChildList] = None
    onAdd: Any = None


class StatTile(ComponentBuilderNode):
    component: str = "StatTile"
    label: Any = None
    value: Any = None


# --------------------------------------------------------------------------
# Small pieces
# --------------------------------------------------------------------------


def bind(path: str) -> DataBinding:
    return DataBinding(path=path)


def formatted(template: str) -> dict[str, Any]:
    """A string with `${...}` read from the data, through `formatString`."""
    return {"@call": "formatString", "args": {"value": template}}


def heading_text(text: str, level: int = 3) -> Text:
    """A heading: in A2UI v1.0, Markdown in a `Text`."""
    return Text(text=f"{'#' * level} {text.lstrip('#').strip()}")


def _event(name: str, context: dict[str, Any], said: str | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {"name": name, "context": context}
    if said:
        event["userMessage"] = formatted(said)
    return {"event": event}


def _chosen(path: str) -> dict[str, Any]:
    """Whether the row being drawn is the one recorded at `path`."""
    return {"@call": "equals", "args": {"a": bind("id"), "b": bind(path)}}


def _hop(value: Any, selected: str = "") -> Optional[int]:
    """Which hop a list is for: the `hop` argument, else the leg `selected` names.

    Hop two is `legs/0`. Accepts a number or a numeric string, since the model
    writes either.
    """
    if not isinstance(value, bool) and value is not None:
        try:
            number = float(str(value).strip())
            if number.is_integer():
                return int(number)
        except ValueError:
            pass
    found = re.search(r"/legs/(\d+)/", selected or "")
    return int(found.group(1)) + 2 if found else None


def _with_hop(hop: Optional[int], **context: Any) -> dict[str, Any]:
    return {**context, "hop": hop} if hop is not None and hop > 1 else context


def _titled(title: str, body: Any) -> Column:
    rows: list[Any] = [heading_text(title)] if isinstance(title, str) and title.strip() else []
    rows.append(body)
    return Column(children=rows)


# --------------------------------------------------------------------------
# The macros
# --------------------------------------------------------------------------


@macro
def flights(heading: str = "", selected: str = "", hop: Any = None) -> Column:
    """A pressable list of the fares `search_flights` returned.

    Binds the rows at `/flights`, so draw it before or after the lookup: it
    fills in when the rows land. With `hop`, it binds that hop's own rows
    (`/fares/N`), so several hops' lists drawn in one turn each keep their
    fares; pass the same `hop` to `search_flights`. Each card says airline,
    number, times, stops and price, and pressing one sends `select_flight`
    with the fare's id, price, airline, number, times and airports.

    Args:
        heading: Optional line above the list, e.g. 'Outbound · JFK → MAD'.
        selected: Path holding the chosen fare, e.g. '/trip/selectedFlight', so
            the chosen card is marked.
        hop: Which hop these fares are for, counted from one (hop two is the
            trip's legs/0); the press carries it.
    """
    which = _hop(hop, selected)
    row = FlightOption(
        airline=bind("airline"),
        departTime=bind("departTime"),
        arriveTime=bind("arriveTime"),
        origin=bind("origin"),
        destination=bind("destination"),
        price=bind("price"),
        duration=bind("duration"),
        stops=bind("stops"),
        flightNumber=bind("flightNumber"),
        total=bind("total"),
        badge=bind("badge"),
        selected=_chosen(selected) if selected else None,
        action=_event(
            "select_flight",
            _with_hop(
                which,
                id=bind("id"),
                price=bind("price"),
                airline=bind("airline"),
                flightNumber=bind("flightNumber"),
                departTime=bind("departTime"),
                arriveTime=bind("arriveTime"),
                **{"from": bind("origin"), "to": bind("destination")},
            ),
            said="Chose ${airline} ${flightNumber}, ${departTime} → ${arriveTime}, ${price}",
        ),
        accessibility={
            "label": formatted(
                "${airline} ${flightNumber}, ${departTime} ${origin} to ${arriveTime}"
                " ${destination}, ${stops}, ${price} ${total}"
            )
        },
    )
    rows = f"/fares/{explicit}" if (explicit := _hop(hop)) is not None else "/flights"
    return _titled(heading, ListOf(children=DynamicChildList(path=rows, template=row)))


@macro
def stays(heading: str = "", selected: str = "", hop: Any = None) -> Column:
    """A pressable list of the stays `search_hotels` returned.

    Binds the rows at `/hotels`; draw it before or after the lookup. With
    `hop`, it binds that hop's own rows (`/rooms/N`); pass the same `hop` to
    `search_hotels`. Pressing a card sends `select_hotel` with the stay's id,
    name and price.

    Args:
        heading: Optional line above the list, e.g. 'Stays in Madrid'.
        selected: Path holding the chosen stay, e.g. '/trip/selectedHotel'.
        hop: Which hop stays the night, counted from one.
    """
    which = _hop(hop, selected)
    row = HotelCard(
        name=bind("name"),
        price=bind("price"),
        neighborhood=bind("neighborhood"),
        rating=bind("rating"),
        amenities=bind("amenities"),
        badge=bind("badge"),
        selected=_chosen(selected) if selected else None,
        action=_event(
            "select_hotel",
            _with_hop(which, id=bind("id"), name=bind("name"), price=bind("price")),
            said="Chose ${name}, ${price}",
        ),
        accessibility={"label": formatted("${name}, ${neighborhood}, rated ${rating}, ${price}")},
    )
    rows = f"/rooms/{explicit}" if (explicit := _hop(hop)) is not None else "/hotels"
    return _titled(heading, ListOf(children=DynamicChildList(path=rows, template=row)))


@macro
def highlights(heading: str = "") -> Column:
    """What a destination is worth going for, as `get_destination` returned it.

    Binds the rows at `/highlights`; draw it before or after the lookup.

    Args:
        heading: Optional line above the list, e.g. 'Worth your time in Berlin'.
    """
    row = ActivityItem(title=bind("name"), note=bind("note"))
    return _titled(heading, ListOf(children=DynamicChildList(path="/highlights", template=row)))


@macro
def itinerary(heading: str = "") -> Column:
    """The day plan recorded on the trip, one card per day.

    Binds `/days`, which the host keeps equal to the `days` you saved with
    `save_trip`, so record the plan there and draw it with this rather than
    writing every activity out. Each activity can be dropped (`drop_activity`
    with its day and index) and each day can ask for more (`add_activity`).

    Args:
        heading: Optional line above the plan, e.g. 'Four days in Berlin'.
    """
    activity = ActivityItem(
        title=bind("title"),
        time=bind("time"),
        category=bind("category"),
        location=bind("location"),
        duration=bind("duration"),
        note=bind("note"),
        done=bind("done"),
        onRemove=_event("drop_activity", {"day": bind("day"), "index": bind("index")}),
    )
    day = ItineraryDay(
        title=bind("title"),
        date=bind("date"),
        summary=bind("summary"),
        children=DynamicChildList(path="activities", template=activity),
        onAdd=_event("add_activity", {"day": bind("day")}),
    )
    return _titled(heading, ListOf(children=DynamicChildList(path="/days", template=day)))


@macro
def trip(heading: str = "", money: Any = False) -> Column:
    """The trip so far, hop by hop: the standing panel.

    Binds `/panel`, which the host keeps current, so it never needs drawing
    again: each hop shows its route, its dates and party, and its fare and stay
    once they are chosen, each with a `change` action naming what and which
    hop. Draw it on the panel, `surface("sidebar")`.

    Args:
        heading: Optional line at the top, e.g. 'Your trip to Madrid'.
        money: True to add what has been committed so far and what is left of
            the budget, once something is priced.
    """
    fare = FlightOption(
        airline=bind("airline"),
        departTime=bind("departTime"),
        arriveTime=bind("arriveTime"),
        origin=bind("origin"),
        destination=bind("destination"),
        price=bind("price"),
        flightNumber=bind("flightNumber"),
        selected=True,
        action=_event("change", {"what": "flight", "hop": bind("hop")}),
        accessibility={"label": formatted("${airline} ${flightNumber}, ${price}")},
    )
    stay = HotelCard(
        name=bind("name"),
        price=bind("price"),
        selected=True,
        action=_event("change", {"what": "stay", "hop": bind("hop")}),
    )
    hop = Column(
        children=[
            Text(text=formatted("#### ${title}")),
            Text(text=bind("when"), variant="caption"),
            ListOf(children=DynamicChildList(path="flights", template=fare)),
            ListOf(children=DynamicChildList(path="stays", template=stay)),
        ]
    )
    rows: list[Any] = [heading_text(heading)] if isinstance(heading, str) and heading.strip() else []
    rows.append(ListOf(children=DynamicChildList(path="/panel/notice", template=Text(text=bind("text")))))
    rows.append(ListOf(children=DynamicChildList(path="/panel/hops", template=hop)))
    if money not in (False, None, "", "false", "no", 0):
        tile = StatTile(label=bind("label"), value=bind("value"))
        rows.append(ListOf(children=DynamicChildList(path="/panel/figures", template=tile)))
    return Column(children=rows)


@macro
def booked(heading: str = "") -> Column:
    """Every flight chosen on the route, in hop order: the answer to "show me
    my flights".

    Binds `/booked`, which the host keeps equal to the fares on the record, so
    nothing is typed out and nothing is left off however many hops there are.
    Each card shows its route and fare, with a `change` action for its hop.

    Args:
        heading: Optional line above the list, e.g. 'Your five flights'.
    """
    fare = FlightOption(
        airline=bind("airline"),
        departTime=bind("departTime"),
        arriveTime=bind("arriveTime"),
        origin=bind("origin"),
        destination=bind("destination"),
        price=bind("price"),
        flightNumber=bind("flightNumber"),
        selected=True,
        action=_event("change", {"what": "flight", "hop": bind("hop")}),
        accessibility={
            "label": formatted("${route}: ${airline} ${flightNumber}, ${departTime} to ${arriveTime}, ${price}")
        },
    )
    return _titled(heading, ListOf(children=DynamicChildList(path="/booked", template=fare)))


MACROS = (flights, stays, highlights, itinerary, trip, booked)

EXPANDER = MacroExpander(list(MACROS))

MACRO_NAMES = frozenset(meta.name for meta in EXPANDER.macros)


def with_macros(catalog: Any) -> Any:
    """The catalog as the model sees it: its components plus the macros."""
    return EXPANDER.transform_to_inference_catalog(catalog)


def expand(messages: Any) -> Any:
    """The messages with every macro replaced by the components it stands for."""
    return EXPANDER.transform_to_transport(list(messages))
