"""The interface, drawn before the data that fills it exists.

A surface used to appear only once the model had finished writing it, which
meant the screen sat empty for as long as searching for flights takes and then
everything arrived at once. The interface should be the *first* thing that
happens, not the last: the moment the agent decides to look something up, the
shape of the answer is already known, so it can be on screen while the
looking-up happens and fill in as results land.

Nothing new is needed for that — it is three messages A2UI already has:

    createSurface     the surface exists
    updateDataModel   seeded with blank rows, so bindings resolve to nothing
    updateComponents  the layout paints, every field pending
      … tool runs …
    updateDataModel   the rows arrive, and the cards fill in

The components are sent **once**. Only the data model changes afterwards, which
is what makes this cheap: no recompile, no re-send of a tree, and the card the
traveller is looking at is not replaced underneath them.

A field that is pending and a field that is empty are told apart by the data
model itself — an unresolved path is pending, a path resolving to an empty
string is empty — so nothing has to be invented to say which.

The model still composes the real surface once it has results, and that
replaces this one under the same id. This is the opening, not the answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

A2uiMessage = dict[str, Any]

#: How many blank rows to lay out.
#:
#: Four, because that is what every provider returns after its own slice — so
#: the skeleton is the size of the thing arriving and the list does not jump
#: when it does. A provider returning fewer would leave blank rows behind,
#: which is why `fill` replaces the whole array rather than patching row by row.
PENDING_ROWS = 4


def _blank_rows(count: int) -> list[dict[str, Any]]:
    """Rows that exist and hold nothing, so a `_template` repeats over them."""
    return [{} for _ in range(count)]


@dataclass(frozen=True)
class _Blueprint:
    #: Where the rows live in the data model.
    path: str
    #: The key the rows arrive under in the tool's result.
    key: str
    #: Express for a surface whose every field is bound and none are filled.
    express: Callable[[str], str]


def _rows(result: Any, key: str) -> list[Any] | None:
    if not isinstance(result, dict):
        return None
    rows = result.get(key)
    return rows if isinstance(rows, list) and rows else None


# `cabin` is absent from the flight row on purpose. It is a plain enum in the
# catalog rather than a bindable common type, so the compiler refuses
# `cabin=$cabin` — correctly, and with a message that says so. A static property
# cannot take part in a surface filled later, which is a real constraint on what
# a skeleton can promise.
_BLUEPRINTS: dict[str, _Blueprint] = {
    "search_flights": _Blueprint(
        path="/flights",
        key="flights",
        express=lambda surface_id: "\n".join(
            [
                f"surface({json.dumps(surface_id)})",
                'head = Text("Finding flights", variant="h3")',
                "row = FlightOption($airline, $departTime, $arriveTime, $origin, $destination, "
                '$price, Event("select_flight", {id: $id, price: $price}), duration=$duration, '
                "stops=$stops, flightNumber=$flightNumber, badge=$badge)",
                "list = List(_template($/flights, row))",
                "root = Column([head, list])",
            ]
        ),
    ),
    "search_hotels": _Blueprint(
        path="/hotels",
        key="hotels",
        express=lambda surface_id: "\n".join(
            [
                f"surface({json.dumps(surface_id)})",
                'head = Text("Finding places to stay", variant="h3")',
                'row = HotelCard($name, $price, Event("select_hotel", {id: $id, name: $name}), '
                "neighborhood=$neighborhood, rating=$rating, badge=$badge)",
                "list = List(_template($/hotels, row))",
                "root = Column([head, list])",
            ]
        ),
    ),
}


@dataclass(frozen=True)
class PendingSurface:
    """A surface painted empty, and the means to fill it."""

    #: Paints the layout with nothing in it. Sent before the tool runs.
    opening: list[A2uiMessage]
    _path: str
    _key: str
    _surface_id: str
    _version: str

    @property
    def path(self) -> str:
        """Where the rows land, so the model can be told not to redraw over them."""
        return self._path

    def rows(self, result: Any) -> list[Any]:
        """The rows this filled with, for the note that goes back to the model."""
        return _rows(result, self._key) or []

    def fill(self, result: Any) -> list[A2uiMessage] | None:
        """The data model update that fills it, or nothing to fill it with."""
        rows = _rows(result, self._key)
        if rows is None:
            return None
        return [
            {
                "version": self._version,
                "updateDataModel": {
                    "surfaceId": self._surface_id,
                    "path": self._path,
                    "value": rows,
                },
            }
        ]


def pending_surface_for(
    tool_name: str,
    surface_id: str,
    parser: Any,
    version: str = "v0.9.1",
) -> PendingSurface | None:
    """The surface a tool is about to fill, if it is one that fills a surface.

    Returns nothing for tools whose answer has no predictable shape — asking
    what the trip costs does not tell you what the model will draw — and a
    skeleton for a shape nobody fills is worse than no skeleton.
    """
    blueprint = _BLUEPRINTS.get(tool_name)
    if blueprint is None:
        return None

    try:
        messages = parser.compile(blueprint.express(surface_id), is_final=True)
    except Exception:  # noqa: BLE001 - any compile failure, same handling
        # A skeleton that will not compile is not worth failing a turn over:
        # the model's own surface still arrives, just without the head start.
        return None

    seed: A2uiMessage = {
        "version": version,
        "updateDataModel": {
            "surfaceId": surface_id,
            "path": blueprint.path,
            "value": _blank_rows(PENDING_ROWS),
        },
    }

    # `createSurface` first, then the blank rows, then the components — so the
    # layout never paints against a data model that does not exist yet.
    created = [message for message in messages if "createSurface" in message]
    rest = [message for message in messages if "createSurface" not in message]

    return PendingSurface(
        opening=[*created, seed, *rest],
        _path=blueprint.path,
        _key=blueprint.key,
        _surface_id=surface_id,
        _version=version,
    )
