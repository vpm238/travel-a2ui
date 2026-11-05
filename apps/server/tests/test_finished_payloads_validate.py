"""Everything the host sends has to pass the SDK's own validator.

The compiler validates the tree the agent wrote. Then the finishing passes run
over it — seeding the trip, binding the commit button, rewriting night counts,
stripping panel actions — and **nothing validated what they produced**. Two of
them emitted shapes the compiler never would have:

  - `labels.py` wrote a 1.0 `DateRangePicker` a `nightsLabel` under the 0.9 key
    `call`, which the schema rejects as an unevaluated property;
  - `commit.py` injected a `Button` with `"label": "Send"`, and a `Button` has
    no `label` — its face is a component named by the required `child` — so
    every renderer drew an empty, unnamed button.

Both passed every test this repository had, because every test checked what
the passes *meant to* do and none asked whether the result was still A2UI.

So this asks, of everything that reaches a renderer: every macro, every catalog
example, every host-composed voice surface, and the specific shapes that
regressed — compiled, expanded, finished, and handed to
`a2ui.utils.renderer_state.validate_payload`, the same check a renderer holding
this catalog makes. A pass that drifts fails here rather than on screen.
"""

from __future__ import annotations

import asyncio
import pathlib
import warnings

import pytest

warnings.filterwarnings("ignore")

from a2ui.utils.renderer_state import validate_payload  # noqa: E402

from travel_a2ui import ROOT  # noqa: E402
from travel_a2ui.brain.builders import build_surface, compile_surface  # noqa: E402
from travel_a2ui.brain.catalog import CATALOG, parser_for  # noqa: E402
from travel_a2ui.brain.express import as_wire  # noqa: E402
from travel_a2ui.brain.finishing import finish  # noqa: E402
from travel_a2ui.brain.macros import expand  # noqa: E402
from travel_a2ui.brain.providers.fixture import FixtureProvider  # noqa: E402

#: A trip far enough along that every macro has something to draw: two hops,
#: a chosen fare on each, a stay, a budget, a day plan.
TRIP = {
    "origin": "JFK",
    "destination": "MAD",
    "startDate": "2027-04-12",
    "endDate": "2027-04-19",
    "travelers": 2,
    "selectedFlight": "IB6250",
    "flightPrice": 412,
    "airline": "Iberia",
    "departTime": "18:40",
    "arriveTime": "08:15",
    "selectedHotel": "h_MAD_1",
    "hotelName": "Hotel Villa Real",
    "nightlyPrice": 210,
    "budget": 3000,
    "currency": "EUR",
    "legs": [
        {
            "origin": "MAD",
            "destination": "JFK",
            "startDate": "2027-04-19",
            "travelers": 2,
            "selectedFlight": "IB6251",
            "flightPrice": 398,
        }
    ],
    "days": [
        {
            "date": "2027-04-12",
            "activities": [{"title": "Arrive", "time": "09:00", "location": "Barajas"}],
        }
    ],
}

#: An airport list, so `Ask()`'s origin picker has options to validate.
AIRPORTS = {
    "origins": [{"label": "New York (JFK)", "value": "JFK"}],
    "destinations": [{"label": "Madrid (MAD)", "value": "MAD"}],
}


def _finished(source: str, surface_id: str = "inline-1", trip: dict | None = None) -> list:
    record = TRIP if trip is None else trip
    compiled = parser_for(surface_id).compile(source, is_final=True)
    return finish(as_wire(expand(compiled, record, AIRPORTS, "EUR")), record)


def _valid(messages: list) -> None:
    __tracebackhide__ = True
    try:
        validate_payload([CATALOG], messages)
    except Exception as error:  # noqa: BLE001 - the message is the assertion
        pytest.fail(f"{type(error).__name__}: {error}")


@pytest.mark.parametrize(
    "call",
    [
        'Ask("Where to next?", "Find flights")',
        'Flights("Outbound")',
        'Stays("Somewhere to sleep")',
        'Highlights("Worth your time")',
        'Trip("Your trip to Madrid")',
        'Trip("Your trip to Madrid", true)',
        'Itinerary("Your week")',
    ],
)
def test_every_macro_finishes_valid(call: str) -> None:
    surface_id = "sidebar" if call.startswith("Trip") else "inline-1"
    _valid(_finished(f'surface("{surface_id}")\nrows = {call}\nroot = Column([rows])', surface_id))


@pytest.mark.parametrize(
    "example",
    sorted((ROOT / "catalogs" / "a2ui-travel" / "examples").glob("*.express")),
    ids=lambda path: path.stem,
)
def test_every_catalog_example_finishes_valid(example: pathlib.Path) -> None:
    source = example.read_text(encoding="utf-8")
    messages = _finished(source, example.stem)
    # An incremental example only updates a surface an earlier payload made, so
    # it is checked as an update — which is how `validate_payload` already
    # treats a payload that does not create the surface it touches.
    _valid(messages)


@pytest.mark.parametrize(
    "tool",
    [
        "show_flight_options",
        "show_hotel_options",
        "show_trip_controls",
        "show_itinerary",
        "show_trip_dashboard",
        "show_price_summary",
    ],
)
def test_every_host_composed_surface_finishes_valid(tool: str) -> None:
    """The voice door draws these itself, so the agent's compiler never sees them."""
    args = {
        "destination": "Madrid",
        "origin": "JFK",
        "date": "2027-04-12",
        "startDate": "2027-04-12",
        "endDate": "2027-04-19",
        "travelers": 2,
        "days": 3,
    }
    surface = asyncio.run(build_surface(tool, args, FixtureProvider(), "2026-11-01", trip=dict(TRIP)))
    _valid(finish(compile_surface(surface), TRIP))


class TestTheShapesThatRegressed:
    """Each of these went out invalid, and none of them failed a test."""

    def test_a_literal_night_count_becomes_a_valid_1_0_call(self) -> None:
        messages = _finished(
            'surface("inline-1")\n'
            'd = DateRangePicker("When", $/trip/startDate, $/trip/endDate, nightsLabel="7 nights")\n'
            "root = Column([d])"
        )
        _valid(messages)
        picker = next(
            node
            for node in messages[0]["createSurface"]["components"]
            if node["component"] == "DateRangePicker"
        )
        assert "@call" in picker["nightsLabel"], picker["nightsLabel"]
        assert "call" not in picker["nightsLabel"], "the 0.9 key, on a 1.0 surface"

    def test_an_injected_commit_button_has_a_face(self) -> None:
        messages = _finished(
            'surface("inline-1")\n'
            'who = TravelerCounter("Travellers", $/trip/travelers, min=1, max=8)\n'
            "root = Column([who])"
        )
        _valid(messages)
        by_id = {node["id"]: node for node in messages[0]["createSurface"]["components"]}
        button = by_id["__commit"]
        assert "label" not in button, "a Button has no label; its face is a child"
        assert by_id[button["child"]]["component"] == "Text"


def _headings_said_twice(messages: list) -> list[str]:
    said: dict[str, list[str]] = {}
    for message in messages:
        body = message.get("createSurface") or message.get("updateComponents") or {}
        # A2UI 1.0 writes a heading as Markdown in the text.
        texts = [
            node["text"].lstrip("#").strip()
            for node in body.get("components", [])
            if node.get("component") == "Text"
            and isinstance(node.get("text"), str)
            and node["text"].startswith("#")
        ]
        said.setdefault(str(body.get("surfaceId")), []).extend(texts)
    return sorted({text for texts in said.values() for text in texts if texts.count(text) > 1})


@pytest.mark.parametrize(
    "example",
    sorted((ROOT / "catalogs" / "a2ui-travel" / "examples").glob("*.express")),
    ids=lambda path: path.stem,
)
def test_no_example_teaches_a_heading_twice(example: pathlib.Path) -> None:
    """The prompt's own example wrote `Text("Outbound …")` above `Flights("Outbound …")`.

    The macro draws its heading, so the example put the line on screen twice —
    and the agent copied it into every fare and stay card it drew. Removing the
    duplicate in the host was tried and reverted: the host does not edit the
    agent's composition. The fix is to stop teaching it, and this keeps it
    taught right.
    """
    assert _headings_said_twice(_finished(example.read_text(encoding="utf-8"), example.stem)) == []
