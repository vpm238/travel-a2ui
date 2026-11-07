"""A route of five hops, and a party asked hop by hop.

A hop that travels with the party before it has no `travelers` of its own on
the record, and a screen reports hops by index and only what it holds. Between
them those made a counter for the fourth hop show nobody, and a submitted form
able to drop the cities, dates and fares of every hop it did not mention. This
holds the route steady through both.
"""

from __future__ import annotations

import copy
from typing import Any

from helpers import FakeModel, base, events_of

from travel_a2ui.brain import data
from travel_a2ui.brain import trip as model
from travel_a2ui.brain.inbound import SurfaceAction
from travel_a2ui.brain.ui import Canvas, Drawing

FIVE_HOPS: dict[str, Any] = {
    "origin": "SFO",
    "destination": "Chicago",
    "startDate": "2027-04-10",
    "endDate": "2027-04-12",
    "travelers": 2,
    "selectedFlight": "DL4766",
    "flightPrice": 167,
    "legs": [
        {
            "origin": "ORD",
            "destination": "New York",
            "startDate": "2027-04-12",
            "endDate": "2027-04-15",
            "selectedFlight": "UA1894",
            "flightPrice": 119,
        },
        {"origin": "JFK", "destination": "Boston", "startDate": "2027-04-15", "endDate": "2027-04-17"},
        {"origin": "BOS", "destination": "Miami", "startDate": "2027-04-17", "endDate": "2027-04-20"},
        {"origin": "MIA", "destination": "SFO", "startDate": "2027-04-20"},
    ],
}

COUNTERS = (
    "<a2ui>\n"
    'surface("inline-1", sendDataModel=true)\n'
    "{defaults}"
    'c0 = TravelerCounter("SFO → Chicago", $/trip/travelers)\n'
    'c1 = TravelerCounter("Chicago → New York", $/trip/legs/0/travelers)\n'
    'c2 = TravelerCounter("New York → Boston", $/trip/legs/1/travelers)\n'
    'c3 = TravelerCounter("Boston → Miami", $/trip/legs/2/travelers)\n'
    'c4 = TravelerCounter("Miami → SFO", $/trip/legs/3/travelers)\n'
    'lbl = Text("Done")\n'
    'go = Button(lbl, "primary", Event("set_party"))\n'
    "root = Column([c0, c1, c2, c3, c4, go])\n"
    "</a2ui>"
)


def drawn_on(canvas: Canvas, trip: dict[str, Any], defaults: str = "") -> dict[str, Any]:
    """Draws the counters and fills them from the record; the renderer's data."""
    values = lambda _s: data.session_values(trip, None)  # noqa: E731
    Drawing(canvas, "inline-1", values).feed(COUNTERS.format(defaults=defaults))
    canvas.provide(values)
    return canvas.data_of("inline-1")


def submitted(canvas: Canvas, trip: dict[str, Any], reported: dict[str, Any]) -> dict[str, Any]:
    action = SurfaceAction(name="set_party", surface_id="inline-1")
    events = events_of(
        base(
            action=action,
            data_model={"inline-1": reported},
            trip=copy.deepcopy(trip),
            client=FakeModel([(["Noted."], [])]),
            canvas=canvas,
        )
    )
    return next(event for event in events if event["type"] == "__result__")["result"].trip


def parties(trip: dict[str, Any]) -> list[Any]:
    return [hop.get("travelers") for hop in model.journey(trip)]


def route(trip: dict[str, Any]) -> list[tuple[Any, Any, Any]]:
    return [(hop.get("from"), hop.get("to"), hop.get("startDate")) for hop in model.journey(trip)]


class TestEveryCounterShowsTheParty:
    def test_a_hop_with_no_party_of_its_own_shows_the_one_it_travels_with(self) -> None:
        shown = drawn_on(Canvas(), FIVE_HOPS)
        assert [leg.get("travelers") for leg in shown["trip"]["legs"]] == [2, 2, 2, 2]
        assert shown["trip"]["travelers"] == 2

    def test_a_default_for_one_hop_leaves_the_others_to_the_record(self) -> None:
        shown = drawn_on(Canvas(), FIVE_HOPS, "$/trip/legs/3/travelers = 3\n")
        legs = shown["trip"]["legs"]
        assert [leg.get("destination") for leg in legs] == ["New York", "Boston", "Miami", "SFO"]
        assert [leg.get("travelers") for leg in legs] == [2, 2, 2, 3]


class TestASubmittedFormKeepsTheRoute:
    def test_one_hop_changed_changes_that_hop_only(self) -> None:
        canvas = Canvas()
        shown = drawn_on(canvas, FIVE_HOPS)
        reported = copy.deepcopy(shown)
        reported["trip"]["legs"][2]["travelers"] = 3
        after = submitted(canvas, FIVE_HOPS, reported)
        assert parties(after) == [2, 2, 2, 3, 2]
        assert route(after) == route(FIVE_HOPS)
        assert after["legs"][0]["selectedFlight"] == "UA1894"

    def test_a_form_that_holds_only_some_hops_cannot_drop_the_rest(self) -> None:
        canvas = Canvas()
        drawn_on(canvas, FIVE_HOPS)
        after = submitted(canvas, FIVE_HOPS, {"trip": {"legs": [None, None, None, {"travelers": 4}]}})
        assert parties(after) == [2, 2, 2, 2, 4]
        assert route(after) == route(FIVE_HOPS)
        assert after["legs"][0]["selectedFlight"] == "UA1894"

    def test_nobody_touching_anything_changes_nothing(self) -> None:
        canvas = Canvas()
        shown = drawn_on(canvas, FIVE_HOPS)
        after = submitted(canvas, FIVE_HOPS, copy.deepcopy(shown))
        assert parties(after) == [2, 2, 2, 2, 2]
        assert route(after) == route(FIVE_HOPS)


class TestTheMergeItself:
    def test_a_hole_says_nothing_about_its_hop(self) -> None:
        patch = model.screen_patch(FIVE_HOPS, {"legs": [None, {}, None, {"travelers": 1}]})
        assert [leg["destination"] for leg in patch["legs"]] == ["New York", "Boston", "Miami", "SFO"]
        assert patch["legs"][3]["travelers"] == 1

    def test_a_screen_can_neither_add_nor_remove_a_hop(self) -> None:
        shorter = model.screen_patch(FIVE_HOPS, {"legs": [{"travelers": 3}]})
        assert len(shorter["legs"]) == 4
        longer = model.screen_patch(FIVE_HOPS, {"legs": [{}, {}, {}, {}, {"destination": "Nowhere"}]})
        assert "legs" not in longer


class TestAHopKeepsItsTicket:
    """What the panel shows about a hop's fare survives the trip being read."""

    TICKETED = {
        **FIVE_HOPS,
        "legs": [
            {
                **FIVE_HOPS["legs"][0],
                "airline": "United",
                "flightNumber": "UA768",
                "departTime": "10:44",
                "arriveTime": "13:12",
            },
            *FIVE_HOPS["legs"][1:],
        ],
    }

    def test_normalising_keeps_a_hops_fare_details(self) -> None:
        leg = model.normalize(self.TICKETED)["legs"][0]
        assert (leg["airline"], leg["flightNumber"], leg["departTime"], leg["arriveTime"]) == (
            "United",
            "UA768",
            "10:44",
            "13:12",
        )

    def test_releasing_the_first_flight_leaves_the_others_alone(self) -> None:
        after, _ = model.release(self.TICKETED, ["selectedFlight"])
        assert "selectedFlight" not in after and "flightPrice" not in after
        assert after["legs"][0]["airline"] == "United" and after["legs"][0]["selectedFlight"] == "UA1894"

    def test_releasing_a_hops_flight_releases_what_came_with_it(self) -> None:
        after, cleared = model.release(self.TICKETED, ["legs/0/selectedFlight"])
        leg = after["legs"][0]
        assert not {"selectedFlight", "flightPrice", "airline", "flightNumber"} & set(leg)
        assert after["selectedFlight"] == "DL4766"
        assert "legs/0/flightPrice" in cleared
