"""The Python trip model has to give the TypeScript model's answers.

Not "similar answers" — the same JSON. Two implementations of the same
judgement that agree on nine trips and disagree on the tenth is the failure
this exists to prevent, and it is one that shows up as an agent asking for
something it already has rather than as anything that looks like a bug.

The golden is produced by `tools/parity/trip-golden.mjs` from the TypeScript.
When the TypeScript goes, the golden stays and becomes the specification.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from travel_a2ui import trip as model

ROOT = pathlib.Path(__file__).resolve().parents[3]
GOLDEN = json.loads((ROOT / "tools" / "parity" / "__golden__" / "trip.json").read_text("utf-8"))

TODAY = "2027-03-01"

TRIP_NAMES = list(GOLDEN["trips"])


def same(actual, expected, what: str) -> None:
    """Compares as serialised JSON, so key order counts.

    Key order is not pedantry here: these objects are sent on the wire and
    diffed against a golden, and a port that produces the right values in a
    different order is a port that will look broken the first time anyone
    compares two payloads.
    """
    assert json.dumps(actual, ensure_ascii=False) == json.dumps(expected, ensure_ascii=False), what


class TestTheTable:
    """The field table is shared data, so this is really a check that it loaded."""

    def test_fields_match(self):
        same(model.FIELDS, GOLDEN["model"]["fields"], "fields")

    def test_requirements_match(self):
        same(model.REQUIREMENTS, GOLDEN["model"]["requirements"], "requirements")

    def test_trip_keys_match(self):
        same(model.TRIP_KEYS, GOLDEN["model"]["tripKeys"], "tripKeys")

    def test_bindings_match(self):
        bindings = {key: model.binding_for(key) for key in model.TRIP_KEYS}
        same(bindings, GOLDEN["model"]["bindings"], "bindings")


class TestCoercion:
    """The shapes a model or a surface really sends, including the wrong ones."""

    @pytest.mark.parametrize("case", GOLDEN["coerce"], ids=lambda c: f"{c['key']}={c['input']!r}")
    def test_coerce(self, case):
        same(model.coerce(case["key"], case["input"]), case["output"], str(case))


class TestPerTrip:
    @pytest.mark.parametrize("name", TRIP_NAMES)
    def test_normalize(self, name):
        raw = GOLDEN["trips"][name]["normalize"]
        # Round-tripping a normalised trip must be a no-op, which is what makes
        # it safe to normalise on the way in *and* on the way out.
        same(model.normalize(raw), raw, name)

    @pytest.mark.parametrize("name", TRIP_NAMES)
    def test_derived_values(self, name):
        want = GOLDEN["trips"][name]
        trip = want["normalize"]

        same(model.nights(trip), want["nights"], f"{name}: nights")
        same(model.problems(trip, TODAY), want["problems"], f"{name}: problems")
        same(model.summarize(trip, TODAY), want["summarize"], f"{name}: summarize")
        same(model.basis_of(trip), want["basisOf"], f"{name}: basisOf")

    @pytest.mark.parametrize("name", TRIP_NAMES)
    def test_readiness(self, name):
        want = GOLDEN["trips"][name]
        trip = want["normalize"]

        for goal in model.REQUIREMENTS:
            same(model.missing_for(trip, goal), want["missingFor"][goal], f"{name}: {goal}")
            same(model.can_do(trip, goal), want["canDo"][goal], f"{name}: canDo {goal}")

    @pytest.mark.parametrize("name", TRIP_NAMES)
    def test_route(self, name):
        want = GOLDEN["trips"][name]
        trip = want["normalize"]

        same(model.stops(trip), want["stops"], f"{name}: stops")
        same(model.journey(trip), want["journey"], f"{name}: journey")
        same(model.party_varies(trip), want["partyVaries"], f"{name}: partyVaries")

    @pytest.mark.parametrize("name", TRIP_NAMES)
    def test_decision_shape(self, name):
        want = GOLDEN["trips"][name]
        same(model.decision_shape(want["normalize"]), want["decisionShape"], f"{name}: shape")

class TestSentences:
    def test_ask_for(self):
        cases = [[], ["destination"], ["destination", "origin"], ["destination", "origin", "startDate"]]
        same([model.ask_for(keys) for keys in cases], GOLDEN["askFor"], "askFor")


class TestMutations:
    @pytest.mark.parametrize("case", GOLDEN["merge"], ids=range(len(GOLDEN["merge"])))
    def test_merge(self, case):
        same(model.merge(model.normalize(case["into"]), case["patch"]), case["result"], str(case))

    @pytest.mark.parametrize("case", GOLDEN["confirm"], ids=range(len(GOLDEN["confirm"])))
    def test_confirm(self, case):
        same(
            model.confirm(model.normalize(case["trip"]), case["fields"]),
            case["result"],
            str(case),
        )

    @pytest.mark.parametrize("case", GOLDEN["release"], ids=range(len(GOLDEN["release"])))
    def test_release(self, case):
        source = GOLDEN["trips"]["chosen"]["normalize"]
        trip, cleared = model.release(source, case["keys"])
        same(trip, case["trip"], f"release {case['keys']}")
        same(cleared, case["cleared"], f"release {case['keys']} cleared")

    @pytest.mark.parametrize("case", GOLDEN["unskip"], ids=range(len(GOLDEN["unskip"])))
    def test_unskip(self, case):
        source = GOLDEN["trips"]["skipped a stage"]["normalize"]
        same(model.unskip(source, case["stage"]), case["result"], str(case))


class TestJavaScriptSemanticsThatDoNotPortForFree:
    """The three that bite, asserted directly rather than through a trip.

    Each of these is a place where the obvious Python is quietly different from
    the JavaScript, and where the difference would show up as a number that is
    off by one somewhere far away from here.
    """

    def test_halves_round_up_not_to_even(self):
        # Python's round(2.5) is 2. Math.round(2.5) is 3.
        assert model.coerce("travelers", 2.5) == 3
        assert model.coerce("travelers", 3.5) == 4

    def test_a_number_with_trailing_rubbish_takes_the_prefix(self):
        # parseFloat("1.2.3") is 1.2; float("1.2.3") raises.
        assert model.coerce("budget", "1.2.3") == 1

    def test_money_arrives_formatted(self):
        assert model.coerce("budget", "$1,240") == 1240

    def test_a_key_with_no_value_is_absent_rather_than_null(self):
        # `JSON.stringify` drops undefined, so a leg with no origin has no
        # `origin` key at all — not `"origin": null`.
        legs = model.stops({"destination": "Madrid"})
        assert "origin" not in legs[0]


class TestAPartyThatChangesAlongTheWay:
    """One number cannot describe a trip that flies home with a different one.

    The case this is about — "NYC to SFO, coming back with two of us" — was
    already in the goldens as "multi-leg, party varies", and the answer captured
    there was `1 traveller`: the outbound count, standing for the whole trip.
    The test passed, because it was asserting that the port reproduced the
    incumbent, and the incumbent was wrong.

    It matters because `basis_of` is what every priced surface puts beside its
    fares. A total for two people under a heading that says one traveller is not
    a cosmetic problem; it is the surface disagreeing with itself about what it
    just quoted.
    """

    OUT_AND_BACK = {
        "origin": "JFK",
        "destination": "SFO",
        "travelers": 1,
        "legs": [{"destination": "JFK", "origin": "SFO", "travelers": 2}],
    }

    def test_a_leg_with_its_own_party_widens_the_basis(self):
        assert model.basis_of(self.OUT_AND_BACK) == "JFK → SFO · 1–2 travellers"

    def test_a_leg_that_agrees_does_not(self):
        """Only a real difference is worth the extra words."""
        trip = {**self.OUT_AND_BACK, "travelers": 2}
        assert model.basis_of(trip) == "JFK → SFO · 2 travellers"

    def test_a_leg_that_says_nothing_does_not(self):
        """An unset leg party means "the same as the trip", not zero."""
        trip = {**self.OUT_AND_BACK, "legs": [{"destination": "JFK"}]}
        assert model.basis_of(trip) == "JFK → SFO · 1 traveller"

    def test_the_per_leg_count_survives_the_round_trip(self):
        """What a surface sends back has to still be there after normalising.

        The counter is bound to `$/trip/legs/0/travelers`, and the whole `/trip`
        subtree is merged back on commit — so if `normalize` dropped a leg's
        party size, the surface would show two people and the trip would go on
        holding one, with nothing on screen to say so.
        """
        normalized = model.normalize(self.OUT_AND_BACK)
        assert normalized["legs"][0]["travelers"] == 2
        assert normalized["travelers"] == 1
        assert model.problems(normalized, TODAY) == []


class TestAFlightPerHop:
    """Every hop is its own ticket, and the trip had nowhere to put the second.

    `selectedFlight` was one trip-level field, so choosing the outbound looked
    like choosing "the flight" — and a leg could not have recorded its own
    anyway, because `normalize` dropped `selectedFlight` off a leg on the way
    in. What the route says about each hop is now `journey`, and it says it hop
    by hop.

    What is deliberately *not* here any more: inventing the hop home. A route
    that ends somewhere other than home is a route with a hop nobody has
    recorded, and noticing that is the agent's job — `prompts/journey.md` — not
    a guess made in Python, which was wrong for every one-way ever typed.
    """

    OUT_AND_BACK = {
        "origin": "JFK",
        "destination": "SFO",
        "startDate": "2027-04-12",
        "endDate": "2027-04-19",
        "travelers": 1,
        "selectedFlight": "UA830",
        "flightPrice": 274,
        "legs": [
            {
                "destination": "NYC",
                "origin": "SFO",
                "travelers": 2,
                "startDate": "2027-04-19",
                "endDate": "2027-04-20",
            }
        ],
    }

    def test_a_leg_can_hold_its_own_flight(self):
        trip = model.normalize(
            {
                "destination": "SFO",
                "legs": [{"destination": "NYC", "selectedFlight": "B6123", "flightPrice": 310}],
            }
        )
        assert trip["legs"][0]["selectedFlight"] == "B6123"
        assert trip["legs"][0]["flightPrice"] == 310

    def test_a_hop_with_no_ticket_says_so_and_the_one_with_a_ticket_does_not(self):
        hops = model.journey(self.OUT_AND_BACK)
        assert [hop["to"] for hop in hops] == ["SFO", "NYC"]
        assert "a ticket" not in hops[0]["wants"], "the outbound is chosen"
        assert "a ticket" in hops[1]["wants"], "SFO → NYC is not"

    def test_each_hop_carries_its_own_party(self):
        """Two out, and someone joins for the second hop."""
        hops = model.journey(self.OUT_AND_BACK)
        assert hops[0]["travelers"] == 1
        assert hops[1]["travelers"] == 2

    def test_a_ticket_on_every_hop_leaves_nothing_wanting_one(self):
        trip = {
            **self.OUT_AND_BACK,
            "legs": [
                {**self.OUT_AND_BACK["legs"][0], "selectedFlight": "B6123"},
                {
                    "destination": "JFK",
                    "origin": "NYC",
                    "startDate": "2027-04-20",
                    "endDate": "2027-04-20",
                    "selectedFlight": "B6200",
                },
            ],
        }
        assert not any("a ticket" in hop["wants"] for hop in model.journey(trip))

    def test_a_hop_they_drive_wants_no_ticket(self):
        """"We'll drive down to Lisbon" is a hop, not a flight."""
        trip = {
            **self.OUT_AND_BACK,
            "legs": [{**self.OUT_AND_BACK["legs"][0], "mode": "car"}],
        }
        hops = model.journey(trip)
        assert hops[1]["mode"] == "car"
        assert "a ticket" not in hops[1]["wants"]

    def test_a_stay_answered_no_stops_being_wanted(self):
        """"Not there, I'm at my sister's" has to be recordable."""
        trip = {
            **self.OUT_AND_BACK,
            "legs": [{**self.OUT_AND_BACK["legs"][0], "needsStay": False}],
        }
        hops = model.journey(trip)
        assert not any("stay" in want for want in hops[1]["wants"])


class TestNightsDecideWhatAHopNeeds:
    """A place you sleep needs a bed and something to do; a connection needs neither.

    Both halves matter. A city with a hotel and an empty itinerary is half a
    plan and the traveler has to ask for the other half; a hotel offered for the
    night they fly home is the question that makes an agent look like a form.
    """

    TRIP = {
        "origin": "SFO",
        "destination": "Chicago",
        "startDate": "2027-04-10",
        "endDate": "2027-04-12",
        "travelers": 1,
        "legs": [
            # Four nights, and somebody joins.
            {
                "destination": "New York",
                "startDate": "2027-04-12",
                "endDate": "2027-04-16",
                "travelers": 3,
            },
            # Home the same day: a connection, not a stay.
            {"destination": "SFO", "startDate": "2027-04-16", "endDate": "2027-04-16"},
        ],
    }

    def hops(self, trip=None):  # noqa: ANN001, ANN201
        return model.journey(trip or self.TRIP)

    def test_a_hop_that_stays_the_night_wants_a_bed_and_a_day(self) -> None:
        chicago = self.hops()[0]
        assert chicago["nights"] == 2
        assert "somewhere to stay" in chicago["wants"]
        assert "things to do" in chicago["wants"]

    def test_a_hop_that_lands_and_leaves_wants_neither(self) -> None:
        home = self.hops()[2]
        assert home["nights"] == 0
        assert not [want for want in home["wants"] if "stay" in want or "things" in want]

    def test_a_stay_they_already_have_still_wants_the_days(self) -> None:
        """"I'm at my sister's" answers the bed, not what they do all week."""
        trip = {**self.TRIP, "selectedHotel": None, "needsStay": False}
        chicago = self.hops(trip)[0]
        assert "somewhere to stay" not in chicago["wants"]
        assert "things to do" in chicago["wants"], "four days there, still unplanned"

    def test_days_already_planned_for_those_dates_answer_it(self) -> None:
        trip = {**self.TRIP, "days": [{"title": "Day one", "date": "2027-04-11"}]}
        assert self.hops(trip)[0]["plannedDays"] == 1
        assert "things to do" not in self.hops(trip)[0]["wants"]

    def test_every_hop_carries_its_own_party_as_its_own_decision(self) -> None:
        """Addressed per hop, so changing one does not undo another."""
        keys = [
            row["key"]
            for hop in self.hops()
            for row in hop["decisions"]
            if row["label"].startswith("who")
        ]
        assert keys == ["travelers", "legs/0/travelers", "legs/1/travelers"]
        assert [hop["travelers"] for hop in self.hops()] == [1, 3, 1]

    def test_releasing_one_hops_party_leaves_the_others_alone(self) -> None:
        released, cleared = model.release(model.normalize(self.TRIP), ["legs/0/travelers"])
        assert cleared == ["legs/0/travelers"]
        assert model.journey(released)[1]["travelers"] == 1, "back to the trip's number"
        assert released["travelers"] == 1, "the trip's own answer is untouched"
