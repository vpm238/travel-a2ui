"""The six surface builders, held to the TypeScript byte for byte.

These are the ones that leave the building. An MCP host installs the plugin and
gets *these* — so a divergence here is not two servers disagreeing with each
other, it is this project disagreeing with itself inside somebody else's
product, where nobody can see the other half to compare.

The refusals are tested as carefully as the answers. "No date was given" and "I
have never heard of Atlantis" are outcomes, not failures, and the exact wording
is the contract: it is what tells the model to draw controls and wait rather
than to price a plausible week.
"""

from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from travel_a2ui.providers.fixture import FixtureProvider
from travel_a2ui.surfaces import build_surface

ROOT = pathlib.Path(__file__).resolve().parents[3]
GOLDEN = json.loads(
    (ROOT / "tools" / "parity" / "__golden__" / "surfaces.json").read_text("utf-8")
)

#: The same fixed day the golden was captured on, so "12 days to Madrid" does
#: not move with the calendar.
TODAY = "2027-03-01"

provider = FixtureProvider()


def run(tool: str, args: dict):
    return asyncio.run(build_surface(tool, args, provider, TODAY))


def where(actual: str, expected: str) -> str:
    """The first line that differs, which is all anyone needs to fix it."""
    a, b = actual.split("\n"), expected.split("\n")
    for index in range(max(len(a), len(b))):
        line_a = a[index] if index < len(a) else "<nothing>"
        line_b = b[index] if index < len(b) else "<nothing>"
        if line_a != line_b:
            return f"line {index + 1}\n  expected: {line_b}\n  actual:   {line_a}"
    return "identical"


@pytest.mark.parametrize("name", list(GOLDEN["surfaces"]))
def test_matches_the_typescript(name: str) -> None:
    case = GOLDEN["surfaces"][name]

    if "error" in case:
        # A refusal, and the message is the contract rather than a detail: it is
        # what tells the model to ask instead of inventing.
        with pytest.raises(Exception) as raised:
            run(case["tool"], case["args"])
        assert str(raised.value) == case["error"], f"{name}: the refusal is worded differently"
        return

    surface = run(case["tool"], case["args"])
    assert surface.express == case["express"], f"{name}: {where(surface.express, case['express'])}"
    assert surface.surface_id == case["surfaceId"], name
    assert surface.summary == case["summary"], name


def test_the_golden_covers_every_surface_tool() -> None:
    """A builder with no case is a builder nobody is holding to anything."""
    covered = {case["tool"] for case in GOLDEN["surfaces"].values()}
    assert covered == {
        "show_flight_options",
        "show_hotel_options",
        "show_trip_controls",
        "show_itinerary",
        "show_trip_dashboard",
        "show_price_summary",
        "render_a2ui_express",
    }


class TestWhatTheSurfacesPromise:
    """Asserted directly, because a golden records what happened, not why."""

    def test_a_flow_decides_how_much_fits(self) -> None:
        # A sidebar column is narrow and a home screen is a summary; the same
        # six flights that read well inline read as a wall in either.
        counts = {}
        for flow, expected in (("inline", 4), ("sidebar", 3), ("home", 2)):
            surface = run(
                "show_flight_options",
                {"destination": "Madrid", "origin": "JFK", "date": "2027-04-12", "surface": flow},
            )
            counts[flow] = surface.express.count("FlightOption(")
            assert counts[flow] == expected, f"{flow} should fit {expected}"

    def test_the_panels_are_singular_and_inline_cards_are_not(self) -> None:
        """Writing to a panel replaces it; that is what makes it a panel."""
        assert run("show_flight_options", {"destination": "Madrid", "origin": "JFK", "date": "2027-04-12", "surface": "sidebar"}).surface_id == "mcp-sidebar"
        assert run("show_hotel_options", {"destination": "Madrid", "surface": "sidebar"}).surface_id == "mcp-sidebar"
        # Two different inline questions get two different cards.
        assert run("show_flight_options", {"destination": "Madrid", "origin": "JFK", "date": "2027-04-12"}).surface_id == "mcp-flights"
        assert run("show_hotel_options", {"destination": "Madrid"}).surface_id == "mcp-hotels"

    def test_every_priced_surface_says_where_the_numbers_came_from(self) -> None:
        """A fare with no provenance on screen is what made this untrustworthy."""
        for tool, args in (
            ("show_flight_options", {"destination": "Madrid", "origin": "JFK", "date": "2027-04-12"}),
            ("show_hotel_options", {"destination": "Madrid", "nights": 4}),
        ):
            surface = run(tool, args)
            assert "Sample data" in surface.express
            assert "Sample data" in surface.summary

    def test_a_widened_search_says_what_it_dropped(self) -> None:
        surface = run(
            "show_flight_options",
            {"destination": "Tokyo", "origin": "LAX", "date": "2027-04-12", "maxPrice": 1},
        )
        assert "Widened:" in surface.express

    def test_the_summary_does_not_recite_the_options(self) -> None:
        """The whole reason a summary exists separately from the surface.

        Handing the model the flight list invites it to read the flight list
        out, which is the one thing the voice mode is for not doing. It gets a
        count and the cheapest fare; the screen holds the rest.
        """
        surface = run(
            "show_flight_options",
            {"destination": "Madrid", "origin": "JFK", "date": "2027-04-12"},
        )
        # Four flights are drawn; at most one fare is spoken.
        assert surface.express.count("FlightOption(") == 4
        fares = [word for word in surface.summary.split() if word.startswith("$")]
        assert len(fares) <= 1, f"the summary quotes {len(fares)} fares: {surface.summary}"

    def test_an_itinerary_never_repeats_a_highlight_while_it_has_new_ones(self) -> None:
        surface = run(
            "show_itinerary", {"destination": "Madrid", "days": 3, "startDate": "2027-04-12"}
        )
        names = [
            line.split("(", 1)[1].split(",", 1)[0]
            for line in surface.express.split("\n")
            if "ActivityItem(" in line
        ]
        assert len(names) == 6
        assert len(set(names)) == len(names), "a plan that lists the same museum twice is a bug"

    def test_a_longer_plan_falls_back_rather_than_repeating(self) -> None:
        surface = run(
            "show_itinerary", {"destination": "Madrid", "days": 7, "startDate": "2027-04-12"}
        )
        assert surface.express.count("ItineraryDay(") == 7
        assert "A slow morning" in surface.express, "the filler carries the days past the highlights"

    def test_over_budget_is_shown_as_over_budget(self) -> None:
        over = run(
            "show_trip_dashboard",
            {"destination": "Madrid", "startDate": "2027-04-12", "nights": 7,
             "travelers": 2, "budget": 1000, "spent": 3200},
        )
        under = run(
            "show_trip_dashboard",
            {"destination": "Madrid", "startDate": "2027-04-12", "nights": 7,
             "travelers": 2, "budget": 4000, "spent": 1200},
        )
        assert '"critical"' in over.express
        assert '"critical"' not in under.express

    def test_the_controls_bind_everything_into_one_button(self) -> None:
        """So the host reads choices out of the surface, not out of a sentence."""
        surface = run("show_trip_controls", {"destination": "Madrid"})
        for path in ("$/filters/start", "$/filters/end", "$/filters/travelers",
                     "$/filters/maxPrice", "$/filters/stops"):
            assert path in surface.express
        apply_line = next(line for line in surface.express.split("\n") if "apply_filters" in line)
        for key in ("start", "end", "travelers", "maxPrice", "stops"):
            assert f"{key}: $/filters/" in apply_line

    def test_a_quote_in_the_data_does_not_break_the_express(self) -> None:
        """Escaping, which fails as a syntax error the model did not make."""
        from travel_a2ui.surfaces import _q

        assert _q("O'Neill's") == '"O\'Neill\'s"'
        assert _q('a "quoted" name') == '"a \\"quoted\\" name"'
        assert _q(None) == '""'


class TestTheRefusals:
    def test_no_date_is_a_refusal_that_says_what_to_ask_for(self) -> None:
        with pytest.raises(Exception) as raised:
            run("show_flight_options", {"destination": "Madrid", "origin": "JFK"})
        message = str(raised.value)
        assert "$/trip/startDate" in message, "it names the binding, so the controls pre-fill"
        assert "flexible: true" in message, "and the deliberate way through"

    def test_flexible_is_the_way_through(self) -> None:
        surface = run(
            "show_flight_options", {"destination": "Madrid", "origin": "JFK", "flexible": True}
        )
        assert "Indicative" in surface.express
        assert "Indicative" in surface.summary

    def test_a_place_nobody_wrote_down_is_drawn_like_any_other(self) -> None:
        """A demo that refuses Atlantis shows a visitor nothing.

        Nine cities have hand-written detail; everywhere else is generated from
        the name, deterministically, and labelled sample data like every other
        figure here. The refusals that remain are for a query naming no place at
        all, and for a trip nobody has described yet — see the case below.
        """
        surface = run(
            "show_flight_options",
            {"destination": "Atlantis", "origin": "JFK", "date": "2027-04-12"},
        )
        assert surface.express
        assert "Atlantis" in surface.summary or "ATL" in surface.express


class TestCatalogFunctionsAreClientSide:
    """Where a catalog function runs, stated rather than inferred.

    All fifteen run in the renderer, against the live data model: that is what
    makes a nights label recompute the instant a date picker moves, with no
    turn, no wait and no tokens. The server composes the call and never
    evaluates one.

    Nothing in the schema said so. You could only find out by noticing there was
    an implementation in `packages/renderer/src/functions.ts` and in
    `lib/functions.dart` and none on the server — which is a fact about where
    code happens to live, not a contract. A third client would have had to
    guess, and guessing wrong means a label that never updates.
    """

    @staticmethod
    def _catalog() -> dict:
        import json
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[3]
        return json.loads((root / "catalogs" / "a2ui-travel" / "catalog.json").read_text("utf-8"))

    def test_every_function_says_where_it_runs(self) -> None:
        functions = self._catalog()["functions"]
        assert functions, "the catalog declares no functions"
        untagged = sorted(n for n, f in functions.items() if "x-runsOn" not in f)
        assert not untagged, f"{untagged} do not say where they run"

    def test_they_all_run_on_the_client(self) -> None:
        """If one ever does not, it needs a server implementation and a test."""
        functions = self._catalog()["functions"]
        assert {f["x-runsOn"] for f in functions.values()} == {"client"}

    def test_the_server_implements_none_of_them(self) -> None:
        """The claim, checked against the code rather than trusted.

        A function quietly implemented on the server would mean two answers to
        one call — the renderer's and the agent's — that agree until they do
        not.
        """
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[3]
        source = "\n".join(
            path.read_text("utf-8")
            for path in (root / "apps" / "server" / "src" / "travel_a2ui").glob("*.py")
        )
        for name in self._catalog()["functions"]:
            assert f"def {name}" not in source, f"{name} has a server implementation"
