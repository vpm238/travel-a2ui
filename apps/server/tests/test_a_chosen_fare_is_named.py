"""A chosen fare is named on the trip panel, however it was chosen.

Reported as "the airline name never appears on the return flight card on the
right panel". A press carries a fare's airline, number and times; a return
chosen out loud, or saved by the agent's own `save_trip`, usually carried an id
and a price. The panel binds what the record has when it is drawn, so that
return was drawn with a blank where its airline goes, and stayed blank.

The host now completes a chosen fare from the fare it offered.
"""

from __future__ import annotations

import asyncio
from typing import Any

from travel_a2ui.brain.presses import complete_chosen_flights
from travel_a2ui.brain.providers.fixture import FixtureProvider
from travel_a2ui.brain.tools import ToolContext, run_tool

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


def saved_by_the_agent(leg: dict[str, Any]) -> dict[str, Any]:
    """`save_trip` as the agent calls it for the return: an id and a price."""
    from travel_a2ui.brain import trip as model

    trip = {**TRIP, "legs": [dict(TRIP["legs"][0])]}

    def save(patch: dict[str, Any]) -> None:
        # As both doors do it.
        merged = model.merge(trip, patch)
        trip.clear()
        trip.update(merged)

    context = ToolContext(trip=trip, provider=FixtureProvider(), save=save, today="2026-11-06")
    asyncio.run(run_tool("save_trip", {"legs": [leg]}, context))
    return trip


class TestTheRecordIsCompleted:
    def test_a_return_saved_by_id_gets_its_airline_and_times(self) -> None:
        leg = saved_by_the_agent({"destination": "JFK", "selectedFlight": "AF3760", "flightPrice": 316})["legs"][0]
        assert leg["airline"] == "Air France"
        assert leg["flightNumber"] == "AF242"
        assert leg["departTime"] == "14:46"
        assert leg["arriveTime"] == "01:00 +1"

    def test_a_return_saved_by_name_and_number_is_found_too(self) -> None:
        leg = saved_by_the_agent({"destination": "JFK", "selectedFlight": "Air France AF242"})["legs"][0]
        assert leg["airline"] == "Air France"
        assert leg["selectedFlight"] == "AF3760", "stored as the fare's own id"
        assert leg["flightPrice"] == 316

    def test_the_outbound_is_left_as_it_was(self) -> None:
        trip = saved_by_the_agent({"destination": "JFK", "selectedFlight": "AF3760"})
        assert trip["airline"] == "TAP Air Portugal"
        assert trip["flightNumber"] == "TP787"

    def test_a_fare_nobody_offered_is_left_alone(self) -> None:
        trip = {**TRIP, "legs": [{**TRIP["legs"][0], "selectedFlight": "ZZ0000"}]}
        done = asyncio.run(complete_chosen_flights(trip, FixtureProvider()))
        assert "airline" not in done["legs"][0]

    def test_a_complete_trip_asks_the_provider_nothing(self) -> None:
        class Counting(FixtureProvider):
            asked = 0

            async def search_flights(self, query: dict[str, Any]):  # noqa: ANN201
                Counting.asked += 1
                return await super().search_flights(query)

        asyncio.run(complete_chosen_flights(dict(TRIP), Counting()))
        assert Counting.asked == 0


class TestThePanelNamesIt:
    def test_the_return_card_binds_its_airline(self) -> None:
        from travel_a2ui.brain import data

        trip = saved_by_the_agent({"destination": "JFK", "selectedFlight": "AF3760", "flightPrice": 316})
        hops = data.panel_rows(trip)["hops"]
        fares = [fare for hop in hops for fare in hop["flights"]]
        assert len(fares) == 2
        assert fares[1]["airline"], "the return is drawn with a blank where its airline goes"
