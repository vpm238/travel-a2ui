"""The four ways a settled trip went on asking to be settled.

Every one of these was reported from the outside as the same thing — "it keeps
showing me the date picker", "it does not save the hotel", "after I picked a
hotel it showed me the flights again" — and every one is a different mechanical
fault. They are together because they share a shape: the host told the model,
turn after turn, that something was still missing which was not, and the model
did the only sensible thing with that and asked for it.

Driven through the model and the tools rather than through a conversation, so
each one names its own cause. The conversations that found them are in
`tools/eval/flow.py`.
"""

from __future__ import annotations

import asyncio

from travel_a2ui.brain import tools, trip as model
from travel_a2ui.brain.controls import half_asked
from travel_a2ui.doors.interactions import _party_paths

TODAY = "2027-03-01"


def _ctx(trip: dict) -> tools.ToolContext:
    """A tool context over a trip, recording nothing else."""
    def save(patch: dict) -> None:
        trip.update(model.normalize(patch))

    return tools.ToolContext(trip=trip, provider=None, save=save, today=TODAY)


def _save(name: str, args: dict, context: tools.ToolContext) -> tuple:
    """One tool call, run to completion. `run_tool` is async; these are not."""
    return asyncio.run(tools.run_tool(name, args, context))


class TestTheHopHome:
    """A hop that arrives and leaves the same day is the way home."""

    SAME_DAY = {
        "destination": "MAD",
        "origin": "JFK",
        "startDate": "2027-04-12",
        "endDate": "2027-04-19",
        "travelers": 2,
        "legs": [
            {
                "destination": "JFK",
                "origin": "MAD",
                "startDate": "2027-04-19",
                "endDate": "2027-04-19",
            }
        ],
    }

    def test_zero_nights_is_not_a_problem(self):
        # The journey brief tells the model to record the hop home exactly like
        # this. It was then refused — "In JFK, 2027-04-19 is not after
        # 2027-04-19" — and because the refusal threw away the whole call, the
        # trip lost its dates and party with it.
        assert model.problems(self.SAME_DAY, TODAY) == []

    def test_a_hop_that_ends_before_it_starts_still_is(self):
        backwards = {
            **self.SAME_DAY,
            "legs": [{**self.SAME_DAY["legs"][0], "endDate": "2027-04-17"}],
        }
        assert [problem["field"] for problem in model.problems(backwards, TODAY)] == ["legs"]
        assert "before" in model.problems(backwards, TODAY)[0]["message"]


class TestTheLastHopIsNotMissingItsDates:
    """Every route ends somewhere, and that hop has no end date to give."""

    ROUTE = {
        "destination": "ORD",
        "origin": "SFO",
        "startDate": "2027-04-10",
        "travelers": 1,
        "legs": [
            {"destination": "JFK", "origin": "ORD", "startDate": "2027-04-12", "travelers": 2},
            {"destination": "SFO", "origin": "JFK", "startDate": "2027-04-16", "travelers": 2},
        ],
    }

    def test_no_hop_wants_dates_once_each_has_a_departure(self):
        # This is the bug behind "it gets the dates thing again": the last hop
        # of every trip ever recorded reported, on every turn, that it was
        # waiting for dates — so the model reached for the tool that asks for
        # dates and drew the picker over whatever was on screen.
        for hop in model.journey(self.ROUTE):
            assert "dates" not in hop["wants"], hop

    def test_a_hop_ends_when_the_next_one_leaves(self):
        route = model.stops(self.ROUTE)
        assert route[0]["endDate"] == "2027-04-12"
        assert route[1]["endDate"] == "2027-04-16"
        assert "endDate" not in route[2]

    def test_so_the_middle_stops_have_nights_and_a_stay_to_ask_about(self):
        hops = model.journey(self.ROUTE)
        assert hops[0]["nights"] == 2
        assert hops[1]["nights"] == 4
        assert "somewhere to stay" in hops[0]["wants"]
        assert "somewhere to stay" in hops[1]["wants"]

    def test_the_last_hop_wants_a_ticket_and_nothing_else(self):
        last = model.journey(self.ROUTE)[-1]
        assert last["last"] is True
        assert last["wants"] == ["a ticket"]

    def test_a_hop_with_no_departure_still_says_so(self):
        undated = {**self.ROUTE, "legs": [{"destination": "JFK", "origin": "ORD"}]}
        assert "dates" in model.journey(undated)[1]["wants"]


class TestOneWay:
    """A journey that is not coming back."""

    def test_the_trip_can_say_so(self):
        # `skip: ["return"]` is what the brief used to ask for, and "return" is
        # not a stage, so it was dropped on the way in and the trip held no
        # record at all — then the next turn read the route, saw it landing in
        # Madrid, and asked about the way home again.
        assert model.coerce("skip", ["return"]) is None
        assert model.coerce("oneWay", True) is True

    def test_it_survives_a_save(self):
        trip: dict = {"destination": "MAD", "origin": "JFK", "startDate": "2027-04-12"}
        result, is_error = _save("save_trip", {"oneWay": True}, _ctx(trip))
        assert is_error is False
        assert result["trip"]["oneWay"] is True

    def test_and_changes_what_the_panel_needs(self):
        settled = {"destination": "MAD", "origin": "JFK", "startDate": "2027-04-12"}
        assert model.decision_shape(settled) != model.decision_shape({**settled, "oneWay": True})


class TestSaveTripKeepsTheSoundHalf:
    """One bad field used to throw away everything in the call with it."""

    SAVED = {
        "destination": "MAD",
        "origin": "JFK",
        "startDate": "2027-04-12",
        "endDate": "2027-04-19",
        "travelers": 2,
    }

    def test_the_stay_is_recorded_even_though_a_hop_is_wrong(self):
        trip = dict(self.SAVED)
        result, is_error = _save(
            "save_trip",
            {
                "selectedHotel": "h_MAD_0",
                "nightlyPrice": 175,
                "legs": [{"destination": "JFK", "startDate": "2027-04-19", "endDate": "2027-04-01"}],
            },
            _ctx(trip),
        )

        assert is_error is False
        assert result["trip"]["selectedHotel"] == "h_MAD_0"
        assert result["trip"]["nightlyPrice"] == 175
        # The route is the part that was wrong, so the route is the part that
        # did not move.
        assert "legs" not in result["trip"]
        assert result["refused"]

    def test_and_the_model_is_told_which_field_to_ask_for_again(self):
        trip = dict(self.SAVED)
        result, _ = _save(
            "save_trip", {"endDate": "2027-04-01", "budget": 4000}, _ctx(trip)
        )
        assert result["trip"]["budget"] == 4000
        assert result["trip"]["endDate"] == "2027-04-19"
        assert "ask the traveler for it again" in result["message"].lower()

    def test_a_sound_call_says_nothing_about_refusals(self):
        trip = dict(self.SAVED)
        result, _ = _save("save_trip", {"selectedFlight": "IB925"}, _ctx(trip))
        assert "refused" not in result
        assert result["trip"]["selectedFlight"] == "IB925"


class TestEveryHopOrNone:
    """A party asked per hop has to be asked of every hop."""

    ROUTE = {
        "destination": "ORD",
        "origin": "SFO",
        "startDate": "2027-04-10",
        "travelers": 1,
        "legs": [
            {"destination": "JFK", "origin": "ORD", "startDate": "2027-04-12"},
            {"destination": "SFO", "origin": "JFK", "startDate": "2027-04-16"},
        ],
    }

    def counters(self, *paths: str) -> list[dict]:
        return [
            {
                "updateComponents": {
                    "components": [
                        {
                            "id": f"who{index}",
                            "component": "TravelerCounter",
                            "label": f"Hop {index}",
                            "value": {"path": path},
                        }
                        for index, path in enumerate(paths)
                    ]
                }
            }
        ]

    def test_the_paths_follow_the_route(self):
        assert _party_paths(self.ROUTE) == (
            "/trip/travelers",
            "/trip/legs/0/travelers",
            "/trip/legs/1/travelers",
        )

    def test_a_single_hop_has_nothing_to_be_inconsistent_about(self):
        alone = {"destination": "MAD", "origin": "JFK", "travelers": 2}
        assert _party_paths(alone) == ()
        assert half_asked(self.counters("/trip/travelers"), ()) is None

    def test_two_counters_over_three_hops_is_sent_back(self):
        # Which is what the brief's own worked example drew.
        complaint = half_asked(
            self.counters("/trip/travelers", "/trip/legs/0/travelers"),
            _party_paths(self.ROUTE),
        )
        assert complaint is not None
        assert "/trip/legs/1/travelers" in complaint
        assert "2 of the 3 hops" in complaint

    def test_all_three_is_fine(self):
        assert (
            half_asked(self.counters(*_party_paths(self.ROUTE)), _party_paths(self.ROUTE))
            is None
        )

    def test_and_so_is_asking_none_of_them(self):
        # A flights surface is not asking about the party at all, and nothing
        # here should make it.
        fares = [
            {
                "updateComponents": {
                    "components": [
                        {"id": "f1", "component": "FlightOption", "origin": {"path": "/trip/origin"}}
                    ]
                }
            }
        ]
        assert half_asked(fares, _party_paths(self.ROUTE)) is None


class TestWhoIsOnAHopThatNobodyAsked:
    def test_an_inherited_party_says_it_is_inherited(self):
        route = {
            "destination": "ORD",
            "origin": "SFO",
            "startDate": "2027-04-10",
            "travelers": 1,
            "legs": [
                {"destination": "JFK", "origin": "ORD", "startDate": "2027-04-12", "travelers": 2},
                {"destination": "SFO", "origin": "JFK", "startDate": "2027-04-16"},
            ],
        }
        hops = model.journey(route)
        assert "partyInherited" not in hops[0]
        assert "partyInherited" not in hops[1]
        assert hops[2]["partyInherited"] is True
        # Still priced for somebody — the default is sensible, it is just not
        # an answer.
        assert hops[2]["travelers"] == 1


class TestTheDaysAreKept:
    """A plan drawn on a card and nowhere else is a plan nobody can use."""

    PLANNED = {
        "destination": "Madrid",
        "origin": "JFK",
        "startDate": "2027-04-12",
        "endDate": "2027-04-19",
        "travelers": 2,
        "selectedFlight": "IB426",
        "selectedHotel": "h_MAD_0",
    }
    DAYS = [
        {
            "title": "Old Madrid on foot",
            "date": "2027-04-13",
            "activities": [
                {"title": "Prado Museum", "time": "10:00", "category": "sight"},
                {"title": "Lunch at Sobrino", "time": "14:00", "category": "food"},
            ],
        }
    ]

    def test_the_schema_can_express_a_day_plan(self):
        # It could not. `days` is a trip field, `share_plan` prints it,
        # `drop_activity` edits it and `journey` counts it — and `save_trip`
        # had no property for it, so nothing could ever write one. A rule the
        # schema cannot express is not a rule anything can follow.
        schema = next(
            tool for tool in tools.TOOLS if tool["name"] == "save_trip"
        )["input_schema"]["properties"]
        assert "days" in schema

    def test_a_planned_hop_stops_asking_for_things_to_do(self):
        trip = dict(self.PLANNED)
        result, is_error = _save("save_trip", {"days": self.DAYS}, _ctx(trip))
        assert is_error is False
        assert result["trip"]["days"][0]["activities"][1]["title"] == "Lunch at Sobrino"
        assert "things to do" not in model.journey(result["trip"])[0]["wants"]

    def test_and_the_shared_page_has_them(self):
        trip = {**self.PLANNED, "days": self.DAYS}
        page, _ = _save("share_plan", {}, _ctx(trip))
        assert "The days" in page["page"]
        assert "Prado Museum" in page["page"]

    def test_dropping_an_activity_has_somewhere_to_drop_it_from(self):
        from travel_a2ui.brain import host_actions

        trip = {**self.PLANNED, "days": self.DAYS}
        patch = host_actions.apply(host_actions.DROP_ACTIVITY, trip, {"day": 0, "index": 0})
        assert patch is not None
        assert [item["title"] for item in patch["days"][0]["activities"]] == ["Lunch at Sobrino"]


class TestTheRefinePanelKnowsTheRoute:
    """The one surface a spoken trip refines itself through.

    It is composed here rather than by the model — an MCP host and a voice call
    get what the server builds — so "one counter per hop" has to hold here too.
    It held one counter for any journey, so a party that changed along the way
    was invisible on the only panel that could have corrected it.
    """

    ROUTE = {
        "destination": "Chicago",
        "origin": "SFO",
        "startDate": "2027-04-10",
        "travelers": 1,
        "legs": [
            {"destination": "New York", "origin": "ORD", "startDate": "2027-04-12", "travelers": 2},
            {"destination": "San Francisco", "origin": "JFK", "startDate": "2027-04-16", "travelers": 2},
        ],
    }

    def panel(self, trip: dict) -> str:
        from travel_a2ui.brain.providers.fixture import FixtureProvider
        from travel_a2ui.brain.surfaces import build_surface

        return asyncio.run(
            build_surface("show_trip_controls", dict(trip), FixtureProvider(), TODAY)
        ).express

    def test_a_counter_for_every_hop(self):
        express = self.panel(self.ROUTE)
        assert express.count("TravelerCounter") == 3
        assert "$/filters/legs/0/travelers" in express
        assert "$/filters/legs/1/travelers" in express

    def test_each_one_is_labelled_by_its_hop_and_pre_filled(self):
        express = self.panel(self.ROUTE)
        assert 'TravelerCounter("ORD → New York"' in express
        assert "$/filters/legs/0/travelers = 2" in express

    def test_and_apply_carries_them_back(self):
        assert "legs: $/filters/legs" in self.panel(self.ROUTE)

    def test_one_hop_is_still_one_counter(self):
        # An MCP host calling the tool cold passes no legs, and gets exactly
        # the panel it always got.
        express = self.panel({"destination": "Madrid", "travelers": 2})
        assert express.count("TravelerCounter") == 1
        assert 'TravelerCounter("Travellers"' in express
        assert "legs:" not in express

    def test_it_compiles(self):
        from travel_a2ui.brain.providers.fixture import FixtureProvider
        from travel_a2ui.brain.surfaces import build_surface, compile_surface

        surface = asyncio.run(
            build_surface("show_trip_controls", dict(self.ROUTE), FixtureProvider(), TODAY)
        )
        nodes = [
            node
            for message in compile_surface(surface)
            for node in (message.get("updateComponents") or {}).get("components") or []
        ]
        assert [node["id"] for node in nodes if node["component"] == "TravelerCounter"] == [
            "who0",
            "who1",
            "who2",
        ]
