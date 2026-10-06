"""A second flight needs somewhere to live, and a press has to say where.

Reported as "the return flight in the sidebar does not get populated in the
flow", and it was three faults stacked on one another. The panel was innocent:
give it a trip whose leg carries a flight and it draws both, always did.
"""

from __future__ import annotations

import json
import pathlib

from travel_a2ui.brain import trip as model
from travel_a2ui.doors.interactions import _leg_pressed

ROOT = pathlib.Path(__file__).resolve().parents[3]
TOOLS = json.loads((ROOT / "data" / "tools.json").read_text("utf-8"))


def _save_trip_leg_properties() -> dict:
    tools = TOOLS["tools"] if isinstance(TOOLS, dict) else TOOLS
    save = next(tool for tool in tools if tool["name"] == "save_trip")
    return save["input_schema"]["properties"]["legs"]["items"]["properties"]


class TestTheToolCanRecordIt:
    """The fault underneath the other two.

    `save_trip`'s leg took `selectedHotel` and `nightlyPrice` but no flight at
    all. Measured, the model did everything right and still failed: it put the
    hop in the press, wrote the leg, saved its origin, dates, party, even
    `selectedHotel: ""` — and dropped the one field it was called about,
    because there was nowhere to put it. A rule the schema cannot express is
    not a rule the model can follow.
    """

    def test_a_leg_can_hold_a_flight(self) -> None:
        props = _save_trip_leg_properties()
        assert "selectedFlight" in props, (
            "a hop after the first has no way to record its ticket, so the "
            "return can only overwrite the outbound"
        )
        assert "flightPrice" in props

    def test_it_can_still_hold_a_stay(self) -> None:
        props = _save_trip_leg_properties()
        assert "selectedHotel" in props and "nightlyPrice" in props


class TestThePressSaysWhichHop:
    def test_the_spellings_the_model_actually_uses(self) -> None:
        """Measured across runs: `leg`, `legIndex`, and `hop` counting from one."""
        assert _leg_pressed({"leg": 0, "id": "IB925"}) == 0
        assert _leg_pressed({"legIndex": 1}) == 1
        assert _leg_pressed({"hop": 2}) == 0, "hop two is the second hop, legs[0]"
        assert _leg_pressed({"hopIndex": 1}) == 0

    def test_a_press_about_nothing_in_particular_names_no_hop(self) -> None:
        assert _leg_pressed({"id": "IB925", "price": 286}) is None
        assert _leg_pressed({}) is None
        assert _leg_pressed(None) is None

    def test_a_flag_is_not_an_index(self) -> None:
        """`True` is an `int` in Python, and would read as hop one."""
        assert _leg_pressed({"leg": True}) is None


class TestTheTicketLandsOnTheHop:
    TRIP = {
        "origin": "JFK",
        "destination": "Madrid",
        "selectedFlight": "IB6250",
        "flightPrice": 412,
        "legs": [{"destination": "JFK", "origin": "MAD", "travelers": 2}],
    }

    def test_the_return_does_not_overwrite_the_outbound(self) -> None:
        out = model.onto_leg(self.TRIP, {"selectedFlight": "IB925", "flightPrice": 286}, 0)
        assert out["selectedFlight"] == "IB6250", "the outbound is the first hop's"
        assert out["legs"][0]["selectedFlight"] == "IB925"
        assert out["legs"][0]["flightPrice"] == 286

    def test_what_the_hop_does_not_own_stays_on_the_trip(self) -> None:
        out = model.onto_leg(self.TRIP, {"selectedFlight": "IB925", "budget": 3000}, 0)
        assert out["budget"] == 3000
        assert "budget" not in out["legs"][0]

    def test_a_hop_that_does_not_exist_is_not_invented(self) -> None:
        """A stale button should do nothing, not grow the route."""
        out = model.onto_leg(self.TRIP, {"selectedFlight": "XX1"}, 4)
        assert len(out["legs"]) == 1
        assert out["legs"][0].get("selectedFlight") is None
        assert out["selectedFlight"] == "IB6250"

    def test_a_trip_with_no_legs_at_all_is_left_alone(self) -> None:
        flat = {"origin": "JFK", "destination": "Madrid", "selectedFlight": "IB6250"}
        assert model.onto_leg(flat, {"selectedFlight": "IB925"}, 0) == flat


class TestThePanelIsToldAboutIt:
    """A ticket bought for a hop is a decision, wherever it is recorded.

    `decision_shape` is what decides whether the panel is rebuilt, and it
    watched the trip's flat fields — which are the *first* hop's. So choosing
    the flight home moved nothing in it, the panel declined to rebuild, and it
    went on reading "Flight · Awaiting selection" under a hop whose flight the
    traveller had just picked, beside an itinerary that already had the flight
    number in it.
    """

    TRIP = {
        "origin": "CPH",
        "destination": "BER",
        "startDate": "2026-10-12",
        "endDate": "2026-10-15",
        "travelers": 2,
        "selectedFlight": "SK8603",
        "legs": [
            {"origin": "BER", "destination": "CPH", "startDate": "2026-10-15", "travelers": 1}
        ],
    }

    def test_the_flight_home_changes_the_shape(self) -> None:
        after = model.onto_leg(self.TRIP, {"selectedFlight": "DY1242"}, 0)
        assert model.decision_shape(after) != model.decision_shape(self.TRIP)

    def test_so_does_a_stay_booked_against_a_hop(self) -> None:
        after = model.onto_leg(self.TRIP, {"selectedHotel": "h_CPH_nyhavn"}, 0)
        assert model.decision_shape(after) != model.decision_shape(self.TRIP)

    def test_and_swapping_it_for_another_changes_it_again(self) -> None:
        one = model.onto_leg(self.TRIP, {"selectedFlight": "DY1242"}, 0)
        two = model.onto_leg(one, {"selectedFlight": "SK503"}, 0)
        assert model.decision_shape(two) != model.decision_shape(one)

    def test_but_a_price_on_its_own_does_not(self) -> None:
        """The fingerprint is decisions, not values: a fare is shown live."""
        after = model.onto_leg(self.TRIP, {"flightPrice": 71}, 0)
        assert model.decision_shape(after) == model.decision_shape(self.TRIP)
