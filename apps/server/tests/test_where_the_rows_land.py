"""The host's whole share of a lookup: the rows, at an address the brief names.

This replaces `test_skeleton_parity.py`, and the thing it no longer tests is
the point. That file held a golden over two Express blueprints the host
compiled at import time — a flight list and a hotel list, layout and fields and
events and four blank rows — because the host drew the cards and the tool
result told the model not to. The interface was in Python.

What is left to test is narrow on purpose: that the rows go where the brief
says they go, that nothing else goes with them, and that a lookup which found
nothing says so by filing nothing rather than by filing an empty array over a
card somebody is reading.
"""

from __future__ import annotations

from typing import Any

import pytest

from travel_a2ui.brain.catalog import PROTOCOL_VERSION
from travel_a2ui.brain.macros import (
    DRAWN_AFTER,
    DRAWN_BY,
    LANDINGS,
    closing_express,
    file_rows,
    landing_for,
    opening_express,
    rows_in,
)

FOUND: dict[str, Any] = {
    "flights": [
        {"id": "DY1234", "airline": "Norwegian", "price": "€281"},
        {"id": "SK119", "airline": "SAS", "price": "€138"},
    ],
    "note": "Sample data",
}


class TestTheAddress:
    def test_the_lookups_with_a_predictable_shape_have_one(self) -> None:
        assert landing_for("search_flights") == "/flights"
        assert landing_for("search_hotels") == "/hotels"
        # The planning half's one predictable shape, and the turn that needed
        # it most: a day plan has nothing to promise until it is written, and
        # writing it is the longest thing the agent says.
        assert landing_for("get_destination") == "/highlights"

    @pytest.mark.parametrize("tool", ["estimate_cost", "get_weather", "save_trip", "get_trip"])
    def test_everything_else_has_none(self, tool: str) -> None:
        """A shape nobody can predict is a promise the brief cannot make.

        `estimate_cost` is the near miss, and it is here rather than above for
        a reason in the protocol: its answer is a list of `{label, amount}`,
        which is exactly a shape — but 1.0 has `DynamicStringList` and no
        dynamic list of *objects*, and `PriceSummary.lines` is static. There is
        no way to bind an itemised total to rows that have not arrived, so it
        is not promised. It is also dispatched last on the turn that totals a
        trip, so promising it would buy nothing.
        """
        assert landing_for(tool) is None
        assert file_rows(tool, FOUND, "inline-1", "v1.0") == []

    def test_the_brief_and_the_host_name_the_same_addresses(self) -> None:
        """The one coupling left between the two sides, so it is asserted.

        The host files rows at `/flights`; the brief tells the agent to write
        `_template($/flights, row)`. If those drift, the agent draws a list
        over an empty path and the cards never appear — and nothing else in
        this suite would notice, because both halves are independently correct.
        """
        import json
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[3]
        catalog = json.loads(
            (root / "catalogs" / "a2ui-travel" / "catalog.json").read_text("utf-8")
        )
        instructions = catalog["instructions"]
        for path, _key in LANDINGS.values():
            assert path in instructions, f"the brief never mentions {path}"


class TestWhatGoesOut:
    def test_one_message_and_it_carries_no_components(self) -> None:
        messages = file_rows("search_flights", FOUND, "inline-7", PROTOCOL_VERSION)
        assert len(messages) == 1
        body = messages[0]
        assert set(body) == {"version", "updateDataModel"}
        assert "createSurface" not in body and "updateComponents" not in body

    def test_the_rows_go_to_the_surface_this_turn_is_answering(self) -> None:
        update = file_rows("search_flights", FOUND, "inline-7", PROTOCOL_VERSION)[0]["updateDataModel"]
        assert update["surfaceId"] == "inline-7"
        assert update["path"] == "/flights"
        assert update["value"] == FOUND["flights"]

    def test_the_whole_array_is_replaced_rather_than_patched(self) -> None:
        """A provider returning three must not leave a fourth behind.

        The agent seeds blank rows to show the shape while the lookup runs, and
        a patch row-by-row would leave the ones it did not reach sitting there
        pending for ever.
        """
        update = file_rows("search_flights", FOUND, "inline-7", PROTOCOL_VERSION)[0]["updateDataModel"]
        assert update["path"] == "/flights", "the array, not an index inside it"
        assert isinstance(update["value"], list)

    def test_it_speaks_the_version_it_is_handed(self) -> None:
        assert (
            file_rows("search_flights", FOUND, "inline-7", PROTOCOL_VERSION)[0]["version"]
            == PROTOCOL_VERSION
        )
        assert file_rows("search_flights", FOUND, "inline-7", "v0.9.1")[0]["version"] == "v0.9.1"

    def test_the_path_keeps_its_unprefixed_spelling(self) -> None:
        """`updateDataModel`'s own `path` is not a binding.

        1.0 reserves `@` for a binding inside a component, and left this key
        alone. Writing `@path` here would be a message no renderer applies.
        """
        update = file_rows("search_flights", FOUND, "inline-7", PROTOCOL_VERSION)[0]["updateDataModel"]
        assert "path" in update and "@path" not in update


class TestALookupThatFoundNothing:
    """A refusal is an answer, and an empty array is not the way to give it."""

    @pytest.mark.parametrize(
        "nothing",
        [None, {}, {"flights": []}, {"flights": "nope"}, "not a dict", 7],
        ids=["none", "empty dict", "empty list", "wrong type", "not a dict", "a number"],
    )
    def test_nothing_is_file_rows(self, nothing: Any) -> None:
        assert rows_in("search_flights", nothing) is None
        assert file_rows("search_flights", nothing, "inline-7", "v1.0") == []

    def test_which_is_not_the_same_as_an_empty_list_of_rows(self) -> None:
        """Filing `[]` would blank a card the traveller is reading.

        "No flights for those dates" is a sentence the agent says; it is not a
        reason to take the last answer off the screen.
        """
        assert file_rows("search_flights", {"flights": []}, "inline-7", "v1.0") == []


class TestTheCardTheAgentAsksFor:
    """`draw:` on a tool call, turned into the macro call that answers it.

    The arguments are positional, and the macros do not take the same ones, so
    this is where a mis-filed `selected` would show up: as a heading.
    """

    def test_a_planning_turn_asks_for_the_highlights(self) -> None:
        express = opening_express(
            "get_destination", {"heading": "Worth your time in Berlin"}, "inline-4"
        )
        assert 'surface("inline-4")' in express
        assert 'Highlights("Worth your time in Berlin")' in express

    def test_and_takes_no_second_argument(self) -> None:
        """A city's highlights have no hop and nowhere to record a choice.

        `Highlights("", "")` is a call the macro cannot accept, so a `draw:`
        carrying keys this macro does not take must drop them rather than pass
        them through as empty strings.
        """
        express = opening_express(
            "get_destination",
            {"heading": "Berlin", "selected": "/trip/selectedHotel", "hop": 2},
            "inline-4",
        )
        assert 'Highlights("Berlin")' in express

    def test_nine_characters_when_there_is_nothing_to_say(self) -> None:
        """The reason a turn will spend them before a lookup it has not run."""
        assert "Highlights()" in opening_express("get_destination", {}, "inline-4")

    def test_a_fare_list_keeps_selected_in_its_own_position(self) -> None:
        """Dropping empties from the end only, never the middle.

        `Flights(selected=…)` with no heading has to stay the *second*
        argument, or the path it records the choice at is drawn as a title.
        """
        express = opening_express(
            "search_flights", {"selected": "/trip/selectedOutbound"}, "inline-2"
        )
        assert 'Flights("", "/trip/selectedOutbound")' in express

    def test_and_a_hop_stays_third(self) -> None:
        express = opening_express("search_flights", {"heading": "Back", "hop": 2}, "inline-3")
        assert 'Flights("Back", "", 2)' in express

    def test_a_tool_with_no_promised_shape_draws_nothing(self) -> None:
        assert opening_express("estimate_cost", {"heading": "What it comes to"}, "inline-5") == ""

    def test_and_neither_does_a_draw_that_is_not_an_object(self) -> None:
        for bad in [None, "heading", 7, []]:
            assert opening_express("get_destination", bad, "inline-4") == ""


class TestTheHighlightsThemselves:
    DESTINATION: dict[str, Any] = {
        "found": True,
        "city": "Berlin",
        "highlights": [
            {"name": "Museum Island", "category": "sight", "note": "Book the Neues"},
            {"name": "Tempelhofer Feld", "category": "outdoors", "note": "Go at golden hour"},
        ],
        "neighbourhoods": ["Mitte"],
    }

    def test_they_land_where_the_macro_reads_them(self) -> None:
        update = file_rows("get_destination", self.DESTINATION, "inline-4", PROTOCOL_VERSION)[0][
            "updateDataModel"
        ]
        assert update["path"] == "/highlights"
        assert update["value"] == self.DESTINATION["highlights"]

    def test_and_nothing_else_on_the_result_goes_with_them(self) -> None:
        """`neighbourhoods` and `places` are for the agent to read, not to draw."""
        messages = file_rows("get_destination", self.DESTINATION, "inline-4", PROTOCOL_VERSION)
        assert len(messages) == 1
        assert set(messages[0]) == {"version", "updateDataModel"}

    def test_a_destination_nobody_has_heard_of_files_nothing(self) -> None:
        """A miss leaves the pre-drawn list empty rather than blanked.

        `get_destination` answers an unknown city with `found: False` and a list
        of the ones it does know — no `highlights`, so nothing is filed, and the
        agent's own sentence is what tells the traveller.
        """
        miss = {"found": False, "message": "No guide for 'Atlantis'.", "available": ["Berlin"]}
        assert rows_in("get_destination", miss) is None
        assert file_rows("get_destination", miss, "inline-4", PROTOCOL_VERSION) == []

    def test_and_so_does_the_call_that_only_lists_cities(self) -> None:
        """`get_destination()` with no argument is a catalogue, not a card."""
        every = {"destinations": [{"city": "Berlin"}, {"city": "Madrid"}]}
        assert file_rows("get_destination", every, "inline-4", PROTOCOL_VERSION) == []


class TestTheCardThatCouldNotBeDrawnFirst:
    """`save_trip`'s own `draw:`, which buys a round rather than a head start.

    Every other `draw:` is about getting a card up before its data arrives.
    This one cannot be: `Itinerary()` reads the trip, so at dispatch it would
    draw "no day plan recorded yet" — the days are still in the arguments. It
    is here because the alternative is a whole further model round whose entire
    output is nine characters and a sentence, measured at 16.7s.
    """

    def test_a_write_is_drawn_after_it_lands_not_before(self) -> None:
        draw = {"heading": "Four days in Berlin"}
        assert opening_express("save_trip", draw, "inline-6") == ""
        assert 'Itinerary("Four days in Berlin")' in closing_express("save_trip", draw, "inline-6")

    def test_and_a_lookup_is_drawn_before_it_lands_not_after(self) -> None:
        """The two tables stay disjoint, or a card is drawn twice."""
        for tool in ("search_flights", "search_hotels", "get_destination"):
            assert closing_express(tool, {"heading": "x"}, "inline-1") == "", tool
        assert set(DRAWN_BY) & set(DRAWN_AFTER) == set()

    def test_it_lands_on_the_surface_the_turn_is_answering(self) -> None:
        express = closing_express("save_trip", {"heading": "Four days"}, "inline-6")
        assert 'surface("inline-6")' in express

    def test_a_save_that_sent_no_heading_draws_nothing(self) -> None:
        """Recording a decision is not a request for a card.

        Most `save_trip` calls are a date or a party size, and drawing a day
        plan over the question that asked for them would be a turn drawing over
        itself.
        """
        assert closing_express("save_trip", None, "inline-6") == ""

    def test_but_an_empty_heading_still_draws_it(self) -> None:
        """`draw: {}` is "yes, with no line above it" — the macro's default."""
        assert "Itinerary()" in closing_express("save_trip", {}, "inline-6")
