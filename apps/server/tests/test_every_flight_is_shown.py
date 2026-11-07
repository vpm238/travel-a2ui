"""Every hop's fares, and every booked flight, on screen when asked for.

A turn that prices two hops searches twice. With one `/flights` for the turn,
the second search's rows replaced the first's in both lists, so the outbound
list showed the flights home. And "show me all my flights" had nothing to bind,
so the model typed the fares out and could leave one off.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from helpers import SETTLED, FakeModel, base, events_of, said_to_model
from test_every_hop_keeps_its_party import FIVE_HOPS

from travel_a2ui.brain import data
from travel_a2ui.brain.inbound import SurfaceAction
from travel_a2ui.brain.ui import Canvas, Drawing
from travel_a2ui.gemini import ToolCall

ROUND_TRIP: dict[str, Any] = {
    **SETTLED,
    "legs": [{"origin": "MAD", "destination": "JFK", "startDate": "2027-04-19"}],
}

TWO_LISTS = (
    "<a2ui>\n"
    'out = Flights("Outbound · JFK → MAD", "/trip/selectedFlight", hop=1)\n'
    'back = Flights("Home · MAD → JFK", "/trip/legs/0/selectedFlight", hop=2)\n'
    "root = Column([out, back])\n"
    "</a2ui>"
)


def search(call_id: str, origin: str, destination: str, date: str, hop: int | None) -> ToolCall:
    args: dict[str, Any] = {"origin": origin, "destination": destination, "date": date}
    if hop is not None:
        args["hop"] = hop
    return ToolCall(id=call_id, name="search_flights", args=args)


def surface_data(events: list[dict[str, Any]], surface_id: str = "inline-1") -> dict[str, Any]:
    """The surface's data model, as the renderer would hold it after the turn."""
    held: dict[str, Any] = {}
    for event in events:
        if event["type"] != "ui" or event["surfaceId"] != surface_id:
            continue
        for message in event["messages"]:
            update = message.get("updateDataModel")
            if update and update.get("path", "").count("/") == 1:
                held[update["path"].strip("/")] = update.get("value")
    return held


def priced_two_hops(out_hop: int | None, back_hop: int | None) -> list[dict[str, Any]]:
    model = FakeModel(
        [
            (
                ["Looking both ways. "],
                [
                    search("c1", "JFK", "Madrid", "2027-04-12", out_hop),
                    search("c2", "MAD", "JFK", "2027-04-19", back_hop),
                ],
            ),
            ([TWO_LISTS], []),
        ]
    )
    return events_of(base(message="price both ways", trip=copy.deepcopy(ROUND_TRIP), client=model, canvas=Canvas()))


class TestEachHopKeepsItsFares:
    def test_two_searches_in_one_turn_fill_two_lists(self) -> None:
        held = surface_data(priced_two_hops(1, 2))
        out, back = held["fares"]["1"], held["fares"]["2"]
        assert out and back
        assert {row["destination"] for row in out} == {"MAD"}
        assert {row["destination"] for row in back} == {"JFK"}

    def test_a_search_that_names_no_hop_is_the_latest_for_every_list(self) -> None:
        held = surface_data(priced_two_hops(None, None))
        assert held["fares"]["1"] == held["fares"]["2"]
        assert {row["destination"] for row in held["fares"]["2"]} == {"JFK"}

    def test_each_list_binds_its_own_hop(self) -> None:
        events = priced_two_hops(1, 2)
        created = json.dumps([event for event in events if event["type"] == "ui"])
        assert '"path": "/fares/1"' in created and '"path": "/fares/2"' in created

    def test_a_hop_with_no_search_of_its_own_still_shows_the_latest(self) -> None:
        values = data.turn_values({"flights": [{"id": "X1"}]}, ROUND_TRIP)
        assert values["fares"]["1"] == values["fares"]["2"] == [{"id": "X1"}]


class TestShowMeAllMyFlights:
    def test_every_booked_fare_is_in_booked_in_hop_order(self) -> None:
        trip = copy.deepcopy(FIVE_HOPS)
        for index, leg in enumerate(trip["legs"]):
            leg.setdefault("selectedFlight", f"XX{index}")
            leg.setdefault("flightPrice", 100 + index)
        booked = data.session_values(trip, None)["booked"]
        assert [row["hop"] for row in booked] == [1, 2, 3, 4, 5]
        assert [row["route"] for row in booked][-1].endswith("SFO")

    def test_booked_draws_them_all(self) -> None:
        trip = copy.deepcopy(FIVE_HOPS)
        for index, leg in enumerate(trip["legs"]):
            leg.setdefault("selectedFlight", f"XX{index}")
        canvas = Canvas()
        values = lambda _s: data.session_values(trip, None)  # noqa: E731
        Drawing(canvas, "inline-1", values).feed('<a2ui>\nb = Booked("Your flights")\nroot = Column([b])\n</a2ui>')
        canvas.provide(values)
        assert len(canvas.data_of("inline-1")["booked"]) == 5


class TestChangeOnThePanel:
    def test_names_the_hop_it_was_pressed_on(self) -> None:
        action = SurfaceAction(name="change", surface_id="sidebar", context={"what": "flight", "hop": 3})
        model = FakeModel([(["Sure."], [])])
        events_of(base(action=action, trip=copy.deepcopy(FIVE_HOPS), client=model, canvas=Canvas()))
        assert "legs/1/selectedFlight" in said_to_model(model, 0)

    def test_the_first_hop_is_the_trips_own_field(self) -> None:
        action = SurfaceAction(name="change", surface_id="sidebar", context={"what": "flight", "hop": 1})
        model = FakeModel([(["Sure."], [])])
        events_of(base(action=action, trip=copy.deepcopy(FIVE_HOPS), client=model, canvas=Canvas()))
        said = said_to_model(model, 0)
        assert "`selectedFlight`" in said and "legs/" not in said.split("pressed")[1].split(".")[0]
