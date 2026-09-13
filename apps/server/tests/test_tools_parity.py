"""The Python tools have to answer what the TypeScript tools answer. Exactly.

The layer these tests cover is the agent's manners: when a tool refuses to
price a trip nobody has given dates for, what it tells the model to do instead,
which stop of a multi-city route a call is about, and what a saved trip reports
still missing. None of it is generated and all of it is judgement, which makes
it the part of the port most likely to drift while every test still passes.

`tools/parity/__golden__/tools.json` is written by the TypeScript and is the
contract. A divergence here is not a formatting difference — every one of these
results is read by a model and turned into a surface, so a port that returns
the right flights under a different key, or drops the sentence telling the
model to draw the controls and wait, ships an agent that is quietly worse at
its job.
"""

from __future__ import annotations

import asyncio
import copy
import json
import pathlib

import pytest

from travel_a2ui.brain.providers.fixture import FixtureProvider
from travel_a2ui.brain import tools
from travel_a2ui.brain.tools import ToolContext, run_tool

ROOT = pathlib.Path(__file__).resolve().parents[3]
GOLDEN = json.loads((ROOT / "tools" / "parity" / "__golden__" / "tools.json").read_text("utf-8"))

#: The same fixed day the golden was captured on. `save_trip` refuses a start
#: date in the past, so without this the test would pass until it didn't.
TODAY = "2027-03-01"


def run_case(case: dict) -> dict:
    """Replays one golden case and reports what this implementation did."""
    trip = copy.deepcopy(case["tripBefore"])
    saved: list[dict] = []

    def save(patch: dict) -> None:
        saved.append(copy.deepcopy(patch))
        trip.update(patch)

    context = ToolContext(
        trip=trip,
        provider=FixtureProvider(),
        save=save,
        today=TODAY,
    )
    result, is_error = asyncio.run(run_tool(case["tool"], case["input"], context))
    return {"result": result, "isError": is_error, "trip": trip, "saved": saved}


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2)


@pytest.mark.parametrize("name", list(GOLDEN))
def test_matches_the_typescript(name: str) -> None:
    expected = GOLDEN[name]
    actual = run_case(expected)

    for field in ("result", "isError", "trip", "saved"):
        assert canonical(actual[field]) == canonical(expected[field]), (
            f"{name}: {field} diverged from the TypeScript"
        )


def test_the_golden_covers_every_tool() -> None:
    """A tool with no case is a tool nobody is holding to anything.

    Cheap to write and it has already earned its place: the port was finished
    before this file existed, and two tools in it answered in a shape the
    TypeScript never used.
    """
    from travel_a2ui.brain.tools import TOOLS

    covered = {case["tool"] for case in GOLDEN.values()}
    assert {tool["name"] for tool in TOOLS} <= covered


class TestGrounding:
    """Search sits beside the tools, and must not leak into the voice setup.

    The eight functions answer with fixtures, which is right for a price nobody
    should trust and poor for the half of planning that is not a price: how many
    days a place deserves, what is shut in April, whether the festival lands in
    their week. Those are facts about the world, and no fixture will ever have
    them.
    """

    def test_the_built_ins_are_declared_in_the_shape_the_api_wants(self) -> None:
        assert tools.grounding_tools() == [
            {"type": "google_search"},
            {"type": "url_context"},
        ]

    def test_a_deployment_can_turn_it_off(self, monkeypatch) -> None:
        """Reaching the open web is the one thing here that leaves the process."""
        monkeypatch.setattr(tools, "GROUNDING", False)
        assert tools.grounding_tools() == []

    def test_the_function_list_stays_functions_only(self) -> None:
        """`voice_tools` reads `name` and `parameters` off every entry.

        A built-in has neither. Putting one in `gemini_tools` would not fail
        here — it would fail when a Live session opened, as a setup frame
        rejected whole with nothing naming the tool that caused it.
        """
        for tool in tools.gemini_tools():
            assert tool["type"] == "function"
            assert tool["name"] and tool["parameters"] is not None

    def test_voice_never_sees_a_built_in(self) -> None:
        from travel_a2ui.doors.live import voice_tools

        for tool in voice_tools():
            assert "name" in tool and "parameters" in tool


class TestATripWithStopsIsCostedStopByStop:
    """One fare times one party size is the wrong total for a real trip.

    `estimate_cost` took the trip's single `flightPrice`, its single
    `travelers` and its single destination and multiplied. A San Francisco →
    Chicago → New York → home trip where a second person joins in Chicago came
    out as one hop for one person: three tickets missing, one of them for two
    people, and the number looked exactly as authoritative as a right one.
    """

    TRIP = {
        "origin": "SFO",
        "destination": "Chicago",
        "startDate": "2027-04-12",
        "endDate": "2027-04-14",
        "travelers": 1,
        "selectedFlight": "UA1",
        "flightPrice": 210,
        "nightlyPrice": 180,
        "legs": [
            {
                "destination": "New York",
                "startDate": "2027-04-14",
                "endDate": "2027-04-18",
                "selectedFlight": "B62",
                "flightPrice": 160,
                "nightlyPrice": 260,
                "travelers": 2,
            },
            {
                "destination": "SFO",
                "startDate": "2027-04-18",
                "endDate": "2027-04-18",
                "selectedFlight": "UA9",
                "flightPrice": 320,
                "travelers": 2,
                "needsStay": False,
            },
        ],
    }

    def _lines(self):
        import asyncio

        from travel_a2ui.brain import trip as model
        from travel_a2ui.brain.providers.fixture import FixtureProvider
        from travel_a2ui.brain.tools import ToolContext, run_tool

        trip = model.normalize(self.TRIP)
        context = ToolContext(
            trip=trip, provider=FixtureProvider(), save=lambda patch: None, today="2027-03-01"
        )
        out, is_error = asyncio.run(run_tool("estimate_cost", {}, context))
        assert not is_error
        return out

    def test_every_hop_is_its_own_line(self):
        out = self._lines()
        labels = [line["label"] for line in out["lines"]]
        assert any("SFO → Chicago" in label for label in labels)
        assert any("Chicago → New York" in label for label in labels)
        assert any("New York → SFO" in label for label in labels)

    def test_a_hop_carries_the_party_that_is_on_it(self):
        out = self._lines()
        first = next(line for line in out["lines"] if "SFO → Chicago" in line["label"])
        later = next(line for line in out["lines"] if "Chicago → New York" in line["label"])
        assert "1 traveler" in first["label"]
        assert "2 travelers" in later["label"]
        # 160 x 2, not 160 x 1 and not 210 x 2.
        assert later["amount"] == "$320"

    def test_the_first_hop_uses_the_trip_s_own_fare(self):
        """The flat fields *are* the first leg; they are flat because most
        trips have one."""
        out = self._lines()
        first = next(line for line in out["lines"] if "SFO → Chicago" in line["label"])
        assert first["amount"] == "$210"
        assert first["note"] == "fare", "priced, not guessed at"

    def test_a_stop_nobody_sleeps_at_has_no_bed_in_it(self):
        out = self._lines()
        assert not any(line["label"].startswith("SFO,") for line in out["lines"])

    def test_each_stay_is_its_own_nights_at_its_own_rate(self):
        out = self._lines()
        chicago = next(line for line in out["lines"] if line["label"].startswith("Chicago,"))
        york = next(line for line in out["lines"] if line["label"].startswith("New York,"))
        assert chicago["amount"] == "$360", "2 nights at 180"
        assert york["amount"] == "$1,040", "4 nights at 260"

    def test_a_one_stop_trip_is_unchanged(self):
        """Which is what keeps the goldens above meaningful."""
        import asyncio

        from travel_a2ui.brain import trip as model
        from travel_a2ui.brain.providers.fixture import FixtureProvider
        from travel_a2ui.brain.tools import ToolContext, run_tool

        trip = model.normalize(
            {
                "origin": "JFK",
                "destination": "Madrid",
                "startDate": "2027-04-12",
                "endDate": "2027-04-19",
                "travelers": 2,
                "flightPrice": 400,
                "nightlyPrice": 150,
            }
        )
        context = ToolContext(
            trip=trip, provider=FixtureProvider(), save=lambda patch: None, today="2027-03-01"
        )
        out, _ = asyncio.run(run_tool("estimate_cost", {}, context))
        labels = [line["label"] for line in out["lines"]]
        assert labels[0].startswith("Flights ("), "still the simple shape"
        assert labels[1].startswith("Stay (")


class TestAPriceIsForTheWholeParty:
    """The number they are choosing between should be the number they pay.

    A fare is per traveller and a room rate is per night, and the cards said
    neither. `$352` sat beside a trip for two and `€121 / night` beside seven
    nights — both correct, both read as the total, and both out by a factor the
    traveller only discovered at the summary.
    """

    TRIP = {
        "origin": "JFK",
        "destination": "Madrid",
        "startDate": "2027-04-12",
        "endDate": "2027-04-19",
        "travelers": 2,
    }

    def result(self, tool: str, trip: dict | None = None) -> dict:
        import asyncio

        from travel_a2ui.brain import tools as tool_module
        from travel_a2ui.brain.providers.fixture import FixtureProvider

        context = tool_module.ToolContext(
            trip=dict(trip or self.TRIP), provider=FixtureProvider(), today=TODAY
        )
        out, _ = asyncio.run(tool_module._run(tool, {"destination": "Madrid"}, context))
        return out

    def test_a_fare_says_what_two_tickets_cost(self) -> None:
        flight = self.result("search_flights")["flights"][0]
        assert flight["units"] == 2
        assert flight["totalValue"] == flight["priceValue"] * 2
        assert "each" in flight["priceLabel"] and "for 2" in flight["priceLabel"]

    def test_one_traveler_is_not_told_it_is_one(self) -> None:
        """"$352 each · $352 for 1" is noise, so the label is just the fare."""
        flight = self.result("search_flights", {**self.TRIP, "travelers": 1})["flights"][0]
        assert flight["priceLabel"] == flight["price"]

    def test_a_room_rate_says_what_the_week_costs(self) -> None:
        stay = self.result("search_hotels")["hotels"][0]
        assert stay["units"] == 7
        assert stay["totalValue"] == stay["priceValue"] * 7

    def test_the_total_is_in_the_currency_it_was_quoted_in(self) -> None:
        """A euro rate totalled in dollars is a figure nobody can act on."""
        out = self.result("search_hotels")
        assert out["currency"] == "EUR"
        assert out["hotels"][0]["total"].startswith("€")
        assert "$" not in out["hotels"][0]["priceLabel"]


class TestAForecastIsPinnedToTheTurnsDay:
    """The one golden that could pass on a Saturday and fail on a Sunday.

    `get_weather` with no start date meant "from today", and today meant the
    wall clock — so the recorded forecast started on whatever weekday the
    golden happened to be captured on and drifted off it the next morning. It
    is not a flake: every other day of the week it was a real, reproducible
    failure of a test that was asserting the calendar rather than the code.

    The fix is the one `save_trip` already used: the turn carries its day, and
    nothing underneath it reaches for the clock.
    """

    def forecast(self, today: str, start_date: str | None = None) -> list[dict]:
        from travel_a2ui.brain.providers.fixture import FixtureProvider

        context = ToolContext(trip={}, provider=FixtureProvider(), today=today)
        args = {"destination": "Madrid"}
        if start_date:
            args["startDate"] = start_date
        out, _ = asyncio.run(run_tool("get_weather", args, context))
        return out["days"]

    def test_the_days_run_from_the_day_the_turn_happens_on(self) -> None:
        # 2027-03-01 is a Monday and 2027-03-06 a Saturday.
        assert self.forecast("2027-03-01")[0]["day"] == "Mon"
        assert self.forecast("2027-03-06")[0]["day"] == "Sat"

    def test_the_same_day_twice_is_the_same_forecast(self) -> None:
        assert self.forecast("2027-03-01") == self.forecast("2027-03-01")

    def test_an_explicit_date_still_wins(self) -> None:
        assert self.forecast("2027-03-01", "2027-04-12")[0]["day"] == "Mon"
        assert self.forecast("2027-03-06", "2027-04-12") == self.forecast(
            "2027-03-01", "2027-04-12"
        )
