"""A fare press lands on the hop the fare flies, whatever `hop` the list was drawn with.

Reported as "choosing the return flight sometimes updates the outgoing flight
on the right for a second and then fixes itself, and sometimes the return
flight still does not have a name". Both came from one place: which hop a fare
press belonged to was read from the `hop` the agent passed when it drew the
list, and the agent passed `hop: 2`, `hop: 1` and nothing at all for the same
return list. A press without one was recorded on the trip's own fields, which
are the outbound's, and the return leg was left to the agent, which saved an id
and a price and nothing the panel could name it by.

A fare card now carries the airports it flies between, and the host matches
them against the route.
"""

from __future__ import annotations

import asyncio
from typing import Any

from travel_a2ui.brain.providers.fixture import FixtureProvider
from travel_a2ui.doors.interactions import SurfaceAction, TurnRequest, run_turn
from travel_a2ui.doors.interactions.press import describe_action, stop_of_fare

TRIP = {
    "origin": "JFK",
    "destination": "Madrid",
    "startDate": "2027-04-12",
    "endDate": "2027-04-19",
    "travelers": 2,
    "selectedFlight": "TP2077",
    "flightPrice": 292,
    "airline": "TAP Air Portugal",
    "flightNumber": "TP787",
    "departTime": "11:00",
    "arriveTime": "21:44",
    "legs": [{"origin": "MAD", "destination": "JFK", "startDate": "2027-04-19"}],
}

RETURN_FARE = {
    "id": "AF3760",
    "price": "€316",
    "from": "MAD",
    "to": "JFK",
    "airline": "Air France",
    "flightNumber": "AF242",
    "departTime": "14:46",
    "arriveTime": "01:00 +1",
}


def stop(context: dict[str, Any], trip: dict[str, Any] = TRIP) -> int | None:
    return asyncio.run(stop_of_fare(context, trip, FixtureProvider()))


class TestTheFareSaysWhereItFlies:
    def test_a_return_fare_is_the_second_stop(self) -> None:
        assert stop(RETURN_FARE) == 1

    def test_an_outbound_fare_is_the_first(self) -> None:
        """`Madrid` on the trip and `MAD` on the fare are one place."""
        assert stop({**RETURN_FARE, "from": "JFK", "to": "MAD"}) == 0

    def test_a_fare_that_flies_neither_hop_decides_nothing(self) -> None:
        assert stop({**RETURN_FARE, "from": "CDG", "to": "LHR"}) is None

    def test_a_fare_with_no_route_decides_nothing(self) -> None:
        assert stop({"id": "AF3760", "hop": 2}) is None

    def test_the_card_carries_its_route(self) -> None:
        """`from`/`to`, never `origin`/`destination`, which are the trip's own."""
        from travel_a2ui.brain.catalog import parser_for
        from travel_a2ui.brain.express import as_wire
        from travel_a2ui.brain.macros import expand

        source = 'f = Flights("Return · MAD → JFK")\nroot = Column([f])'
        wire = as_wire(expand(parser_for("inline-1").compile(source, is_final=True), TRIP))
        card = next(
            node
            for node in wire[0]["createSurface"]["components"]
            if node.get("component") == "FlightOption"
        )
        context = card["action"]["event"]["context"]
        assert context["from"] == {"@path": "origin"}
        assert context["to"] == {"@path": "destination"}
        assert "origin" not in context and "destination" not in context


def pressed(context: dict[str, Any]) -> dict[str, Any]:
    """The trip after a press, through the real turn, with a model that says nothing."""
    from test_interactions import FakeModel  # noqa: PLC0415

    request = TurnRequest(
        api_key="not-a-real-key",
        model="gemini-3-pro-preview",
        provider=FixtureProvider(),
        shape=None,
        trip=dict(TRIP, legs=[dict(leg) for leg in TRIP["legs"]]),
        action=SurfaceAction(name="select_flight", surface_id="inline-2", context=context),
        client=FakeModel([(["Noted."], [])]),
    )

    async def drain() -> list[dict[str, Any]]:
        return [event async for event in run_turn(request)]

    results = [event for event in asyncio.run(drain()) if event["type"] == "__result__"]
    return results[-1]["result"].trip


class TestTheReturnLandsOnTheReturn:
    def test_with_no_hop_at_all(self) -> None:
        trip = pressed(RETURN_FARE)
        leg = trip["legs"][0]
        assert leg["airline"] == "Air France", "the return card has no name to draw"
        assert leg["flightNumber"] == "AF242"
        assert leg["selectedFlight"] == "AF3760"
        assert trip["airline"] == "TAP Air Portugal", "the outbound card showed the flight home"
        assert trip["flightNumber"] == "TP787"

    def test_with_the_wrong_hop(self) -> None:
        """`hop: 1` is what the agent wrote for a return list; the route wins."""
        trip = pressed({**RETURN_FARE, "hop": 1})
        assert trip["legs"][0]["airline"] == "Air France"
        assert trip["airline"] == "TAP Air Portugal"

    def test_and_the_model_is_told_it_was_the_return(self) -> None:
        action = SurfaceAction(name="select_flight", surface_id="inline-2", context=RETURN_FARE)
        assert "legs[0]" in describe_action(action, 0)
        assert "legs[" not in describe_action(action, None)
