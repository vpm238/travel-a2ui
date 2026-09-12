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

    def test_stages_match(self):
        same(model.STAGES, GOLDEN["model"]["stages"], "stages")

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
        same(model.stay_status(trip), want["stayStatus"], f"{name}: stayStatus")
        same(model.party_varies(trip), want["partyVaries"], f"{name}: partyVaries")

    @pytest.mark.parametrize("name", TRIP_NAMES)
    def test_plan(self, name):
        want = GOLDEN["trips"][name]
        trip = want["normalize"]

        same(model.plan(trip), want["plan"], f"{name}: plan")
        same(model.decision_shape(trip), want["decisionShape"], f"{name}: decisionShape")

    @pytest.mark.parametrize("name", TRIP_NAMES)
    def test_next_step(self, name):
        """The sentence that goes straight into the prompt.

        Worth comparing exactly rather than loosely: it is the instruction that
        decides whether the agent leads or stalls politely, and a port that
        rephrases it has changed the agent's behaviour without changing a test.
        """
        want = GOLDEN["trips"][name]
        same(model.next_step_for(want["normalize"]), want["nextStepFor"], f"{name}: nextStepFor")


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
