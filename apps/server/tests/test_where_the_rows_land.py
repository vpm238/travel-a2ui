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
    SEEDED_ROWS,
    clear_rows,
    closing_express,
    file_rows,
    landing_for,
    opening_express,
    rows_in,
    seed_rows,
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
        assert file_rows(tool, FOUND, "inline-1", PROTOCOL_VERSION) == []

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
        assert file_rows("search_flights", nothing, "inline-7", PROTOCOL_VERSION) == []

    def test_which_is_not_the_same_as_an_empty_list_of_rows(self) -> None:
        """Filing `[]` would blank a card the traveller is reading.

        "No flights for those dates" is a sentence the agent says; it is not a
        reason to take the last answer off the screen.
        """
        assert file_rows("search_flights", {"flights": []}, "inline-7", PROTOCOL_VERSION) == []


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
        draw = {"macro": "Itinerary", "heading": "Four days in Berlin"}
        assert opening_express("save_trip", draw, "inline-6") == ""
        assert 'Itinerary("Four days in Berlin")' in closing_express("save_trip", draw, "inline-6")

    def test_and_a_lookup_is_drawn_before_it_lands_not_after(self) -> None:
        """The two tables stay disjoint, or a card is drawn twice."""
        for tool in ("search_flights", "search_hotels", "get_destination"):
            assert closing_express(tool, {"heading": "x"}, "inline-1") == "", tool
        assert set(DRAWN_BY) & set(DRAWN_AFTER) == set()

    def test_it_lands_on_the_surface_the_turn_is_answering(self) -> None:
        express = closing_express(
            "save_trip", {"macro": "Itinerary", "heading": "Four days"}, "inline-6"
        )
        assert 'surface("inline-6")' in express

    def test_a_save_that_sent_no_heading_draws_nothing(self) -> None:
        """Recording a decision is not a request for a card.

        Most `save_trip` calls are a date or a party size, and drawing a day
        plan over the question that asked for them would be a turn drawing over
        itself.
        """
        assert closing_express("save_trip", None, "inline-6") == ""

    def test_but_a_named_macro_with_no_heading_still_draws_it(self) -> None:
        """"Yes, with no line above it" — the macro's own default."""
        assert "Itinerary()" in closing_express("save_trip", {"macro": "Itinerary"}, "inline-6")

    def test_the_opening_turn_draws_its_form_from_the_same_write(self) -> None:
        """The slowest turn in the app, and the one with no lookup to draw ahead of.

        Nothing is known, so there is nothing to look up and nothing to promise;
        the agent's own `Ask()` block arrives only once it has finished thinking,
        measured at 21.4s. The write happens at 10.8s.
        """
        express = closing_express(
            "save_trip", {"macro": "Ask", "heading": "Madrid in April"}, "inline-1"
        )
        assert 'Ask("Madrid in April")' in express

    def test_and_passes_the_button_label_through(self) -> None:
        express = closing_express(
            "save_trip", {"macro": "Ask", "heading": "Madrid", "label": "Price it"}, "inline-1"
        )
        assert 'Ask("Madrid", "Price it")' in express

    def test_a_write_must_name_which_card_it_means(self) -> None:
        """A lookup implies its card; a write does not.

        `save_trip` records a date as readily as a four-day plan, so a `draw:`
        with no macro in it is not a request for anything.
        """
        assert closing_express("save_trip", {"heading": "Four days"}, "inline-6") == ""

    def test_and_may_only_name_one_a_write_can_actually_draw(self) -> None:
        """A lookup's own card is not a write's to ask for."""
        for bogus in ("Flights", "Stays", "Highlights", "", "Ask()", "Column"):
            assert closing_express("save_trip", {"macro": bogus}, "inline-1") == "", bogus

    def test_the_panel_is_one_of_them_and_goes_to_the_panel(self) -> None:
        """`Trip()` is the standing panel, so naming it must not put a sidebar on a card.

        The host used to redraw the panel itself whenever `decision_shape`
        moved. Making it the agent's to ask for is what replaced that, and
        `DRAWS_ONTO` is why asking for it in a call addressed to `inline-7`
        still lands on the panel.
        """
        express = closing_express("save_trip", {"macro": "Trip", "heading": "Berlin"}, "inline-7")
        assert 'surface("sidebar")' in express, express
        assert "inline-7" not in express, express
        assert 'Trip("Berlin")' in express, express

    def test_while_the_itinerary_still_lands_on_the_turn_s_own_card(self) -> None:
        express = closing_express(
            "save_trip", {"macro": "Itinerary", "heading": "Four days"}, "inline-7"
        )
        assert 'surface("inline-7")' in express, express
        assert "sidebar" not in express, express


class TestTheShapeShownWhileTheLookupRuns:
    """Blank rows, so a card drawn before its data is something to look at.

    This was the missing half of drawing-before-the-lookup, and without it the
    other half did nothing visible: `Flights()` is one template over
    `/flights`, a template over an empty array iterates nothing, and the card
    went up on time and rendered blank space until the rows landed. Which is
    the wait it was added to remove.
    """

    def test_a_promised_lookup_gets_placeholders_at_its_own_address(self) -> None:
        messages = seed_rows("search_flights", "inline-2", PROTOCOL_VERSION)
        assert len(messages) == 1
        update = messages[0]["updateDataModel"]
        assert update["path"] == "/flights"
        assert update["surfaceId"] == "inline-2"
        assert update["value"] == [{}, {}, {}]

    def test_the_rows_are_empty_rather_than_fake(self) -> None:
        """`{}` and not `{"airline": "…"}`.

        The renderer's rule is that an unresolvable path is pending and an
        empty string is empty, so a blank row shimmers and an invented one
        would read as a real fare that happened to be called nothing. It is
        also why this needs no loading flag and no second component: the
        skeleton *is* the card, with no data in it.
        """
        rows = seed_rows("search_hotels", "inline-3", PROTOCOL_VERSION)[0]["updateDataModel"]
        assert rows["value"] == [{}] * SEEDED_ROWS
        assert all(row == {} for row in rows["value"])

    @pytest.mark.parametrize("tool", ["estimate_cost", "get_weather", "save_trip"])
    def test_a_tool_with_no_promised_shape_seeds_nothing(self, tool: str) -> None:
        assert seed_rows(tool, "inline-2", PROTOCOL_VERSION) == []
        assert clear_rows(tool, "inline-2", PROTOCOL_VERSION) == []

    def test_the_planning_turn_gets_them_too(self) -> None:
        update = seed_rows("get_destination", "inline-4", PROTOCOL_VERSION)[0]["updateDataModel"]
        assert update["path"] == "/highlights"


class TestWhenTheLookupFoundNothing:
    """The one time filing `[]` is right, and why it is the only one."""

    def test_the_placeholders_are_taken_away(self) -> None:
        update = clear_rows("search_flights", "inline-2", PROTOCOL_VERSION)[0]["updateDataModel"]
        assert update["path"] == "/flights"
        assert update["value"] == []

    def test_which_is_the_opposite_of_what_file_rows_does(self) -> None:
        """Both are correct, and the difference is who put the rows there.

        `file_rows` answers a refusal with no message at all, because filing
        `[]` over a list the traveller is reading takes the last answer off the
        screen. `clear_rows` is for rows this host seeded three seconds ago,
        which nobody is reading and which otherwise shimmer for ever about a
        search that is over.
        """
        assert file_rows("search_flights", {"flights": []}, "inline-2", PROTOCOL_VERSION) == []
        assert clear_rows("search_flights", "inline-2", PROTOCOL_VERSION) != []

    def test_they_are_cleared_at_the_same_address_they_were_seeded(self) -> None:
        for tool in ("search_flights", "search_hotels", "get_destination"):
            seeded = seed_rows(tool, "inline-1", PROTOCOL_VERSION)[0]["updateDataModel"]
            cleared = clear_rows(tool, "inline-1", PROTOCOL_VERSION)[0]["updateDataModel"]
            assert seeded["path"] == cleared["path"] == landing_for(tool), tool


class TestWhatAPressOnALaterHopIsToldToSave:
    """The sentence that decides whether hop two's card has an airline on it.

    `describe_action` already said "whatever it settled belongs on `legs[N]`",
    and the model read "it settled" as the flight id: `legs[0].selectedFlight`
    landed on every run, `airline`, `departTime` and `arriveTime` never did —
    through two live walkthroughs and two rewrites of the same rule, once in
    the flow brief and once in `save_trip`'s argument descriptions.

    The host knows which facts the press carries, because the macro put them
    in the context. Naming them is the one thing a general rule cannot do.
    """

    def said(self, name: str, context: dict[str, Any]) -> str:
        from travel_a2ui.doors.interactions.press import SurfaceAction, describe_action

        return describe_action(
            SurfaceAction(name=name, surface_id="inline-3", context=context)
        )

    FARE = {
        "id": "SK2916",
        "price": "€74",
        "airline": "SAS",
        "departTime": "19:05",
        "arriveTime": "20:15",
        "hop": 2,
    }
    STAY = {"id": "h_BER_x", "name": "Pension Savignyplatz", "price": "€112", "hop": 2}

    def test_a_fare_press_names_every_fact_it_carries(self) -> None:
        said = self.said("select_flight", self.FARE)
        for field in ("selectedFlight", "flightPrice", "airline", "departTime", "arriveTime"):
            assert field in said, f"{field} is not named: {said}"

    def test_and_says_which_leg(self) -> None:
        assert "`legs[0]`" in self.said("select_flight", self.FARE)
        assert "hop 2" in self.said("select_flight", self.FARE)

    def test_a_stay_press_is_told_about_a_stay_and_not_a_flight(self) -> None:
        """`id` and `price` mean different fields depending on what was pressed.

        One shared mapping told a traveller choosing a hotel to save it as
        `selectedFlight`.
        """
        said = self.said("select_hotel", self.STAY)
        assert "selectedHotel" in said and "hotelName" in said and "nightlyPrice" in said
        assert "selectedFlight" not in said, said
        assert "flightPrice" not in said, said

    def test_a_press_on_the_first_hop_is_not_sent_to_a_leg(self) -> None:
        """Hop one is the trip's own fields; `legs[-1]` is nobody's."""
        said = self.said("select_flight", {k: v for k, v in self.FARE.items() if k != "hop"})
        assert "legs[" not in said

    def test_a_press_nobody_has_a_mapping_for_still_says_where(self) -> None:
        said = self.said("pick_something", {"id": "x", "hop": 2})
        assert "`legs[0]`" in said
        assert "That means" not in said, "invented a mapping it does not have"

    def test_only_fields_the_press_actually_carried(self) -> None:
        said = self.said("select_flight", {"id": "SK2916", "hop": 2})
        assert "selectedFlight" in said
        assert "airline" not in said, said


class TestTheContractAndTheHostAgreeOnWhatAWriteMayDraw:
    """`DRAWN_AFTER` is what the host accepts; the tool schema is what the agent reads.

    They have to be the same list. `Trip` was added to `DRAWN_AFTER` so the agent
    could ask for the panel instead of the host redrawing it, and the enum in
    `data/tools.json` still said `["Ask", "Itinerary"]` — so the one path that
    was supposed to replace the host's redraw could not be reached at all. The
    panel fell back to a whole extra model turn and the measurement said the
    change had made things slower, which it had, because the feature was not
    actually on.
    """

    @staticmethod
    def _enum() -> list[str]:
        import json
        import pathlib

        from travel_a2ui import ROOT

        tools = json.loads((pathlib.Path(ROOT) / "data" / "tools.json").read_text("utf-8"))
        for tool in tools["tools"]:
            if tool["name"] == "save_trip":
                return tool["input_schema"]["properties"]["draw"]["properties"]["macro"]["enum"]
        raise AssertionError("save_trip is not in data/tools.json")

    def test_the_agent_is_offered_exactly_what_the_host_accepts(self) -> None:
        from travel_a2ui.brain.macros import DRAWN_AFTER

        assert sorted(self._enum()) == sorted(DRAWN_AFTER["save_trip"]), (
            "the agent is being offered macros the host refuses, or denied ones it "
            "accepts — either way a draw it asks for silently does nothing"
        )

    def test_and_every_one_of_them_compiles(self) -> None:
        """An enum entry that is not a real macro is an instruction to fail."""
        for macro in self._enum():
            express = closing_express(
                "save_trip", {"macro": macro, "heading": "x", "label": "y"}, "inline-1"
            )
            assert express, f"{macro} is offered to the agent but draws nothing"
            assert f"{macro}(" in express, f"{macro} compiled to something else: {express}"


class TestAGuessIsNotAnAnswer:
    """A field the agent assumed still gets asked about.

    "I want to go to Madrid in April with my partner" names no dates. The agent
    picks a plausible week and records it as `assumed`, which is right — a
    starting point beats an empty form. Then `Ask()` tested
    `record.get("startDate")`, found April 11th and drew no date control, while
    the same turn said out loud "let's set your exact April dates". There was
    nowhere to set them, and the trip went on to be priced for a week nobody
    had chosen.

    The picker is bound to the path the assumption is already in, so the
    traveller sees the week the agent chose and either changes it or presses
    the button.
    """

    @staticmethod
    def _controls(trip: dict, airports: dict | None = None) -> list[str]:
        from travel_a2ui.brain.catalog import parser_for
        from travel_a2ui.brain.express import as_wire
        from travel_a2ui.brain.macros import expand

        source = 'surface("inline-1")\nform = Ask("What is still missing?")\nroot = Column([form])'
        drawn = as_wire(
            expand(
                parser_for("inline-1").compile(source, is_final=True),
                trip,
                airports,
            )
        )
        return [c["component"] for c in drawn[0]["createSurface"]["components"]]

    def test_an_assumed_date_still_gets_a_picker(self) -> None:
        guessed = {
            "destination": "MAD",
            "origin": "JFK",
            "travelers": 2,
            "startDate": "2027-04-11",
            "endDate": "2027-04-18",
            "assumed": ["startDate", "endDate"],
        }
        assert "DateRangePicker" in self._controls(guessed), (
            "the dates were invented and the form did not ask about them"
        )

    def test_while_a_date_the_traveller_gave_does_not(self) -> None:
        """The same trip with the dates confirmed asks nothing about them."""
        given = {
            "destination": "MAD",
            "origin": "JFK",
            "travelers": 2,
            "startDate": "2027-04-11",
            "endDate": "2027-04-18",
        }
        assert "DateRangePicker" not in self._controls(given), (
            "a date the traveller gave is being asked for again"
        )

    def test_and_an_assumed_origin_gets_its_picker_back(self) -> None:
        airports = {
            "from": [{"value": "JFK", "label": "New York (JFK)"},
                     {"value": "EWR", "label": "Newark (EWR)"}],
            "to": [],
        }
        guessed = {
            "destination": "MAD",
            "origin": "JFK",
            "travelers": 2,
            "startDate": "2027-04-11",
            "endDate": "2027-04-18",
            "assumed": ["origin"],
        }
        assert "ChoicePicker" in self._controls(guessed, airports), (
            "the agent picked an airport out of three and did not offer the other two"
        )
        settled = {**guessed}
        settled.pop("assumed")
        assert "ChoicePicker" not in self._controls(settled, airports)


class TestAHostDrawnCardIsFinishedLikeAnyOther:
    """The card the host draws from `draw:` goes through `finish` too.

    An agent's own block does: `finish(stack_blocks(on_its_own_surface(...)))`.
    The two host paths — `opening_express` for a lookup's pre-draw and
    `closing_express` for the card a write asks for — yielded their messages
    raw. So no `seed_surface_trip`, and a control on a host-drawn card opened
    empty over a trip that knew the answer.

    Which is the whole of "why does it not auto-fill the form", because
    `save_trip({draw: {macro: "Ask"}})` is the opening form — the one that saves
    a round, and therefore the one most travellers see first. Say "a two week
    trip to Madrid starting next week Friday, four of us" and the agent records
    every word of it, draws the form to confirm, and the form came up blank and
    asked for the party again.
    """

    @staticmethod
    def _drawn(express: str, trip: dict) -> dict:
        """The data model of the surface this Express produces, host-side."""
        from travel_a2ui.brain.catalog import parser_for
        from travel_a2ui.brain.express import as_wire
        from travel_a2ui.brain.finishing import finish
        from travel_a2ui.brain.macros import expand

        drawn = finish(
            as_wire(expand(parser_for("inline-1").compile(express, is_final=True), trip)),
            trip,
        )
        return (drawn[0]["createSurface"].get("dataModel") or {}).get("trip") or {}

    TRIP = {
        "destination": "Madrid",
        "startDate": "2026-11-13",
        "endDate": "2026-11-27",
        "travelers": 4,
    }

    def test_the_opening_form_opens_on_what_was_already_said(self) -> None:
        seeded = self._drawn(
            'surface("inline-1")\nform = Ask("What is still missing?")\nroot = Column([form])',
            self.TRIP,
        )
        assert seeded.get("travelers") == 4, "the party counter opened empty"
        assert seeded.get("startDate") == "2026-11-13", "the dates opened empty"
        assert seeded.get("endDate") == "2026-11-27"
        assert seeded.get("destination") == "Madrid"

    def test_and_so_does_a_lookup_s_pre_drawn_card(self) -> None:
        seeded = self._drawn(
            'surface("inline-1")\nrows = Flights("Outbound")\nroot = Column([rows])',
            self.TRIP,
        )
        assert seeded.get("travelers") == 4, "a pre-drawn card was never seeded"

    def test_both_host_draws_run_through_finish(self) -> None:
        """Asserted on the source, because a missing pass is silent on screen."""
        import inspect

        from travel_a2ui.doors.interactions import turn as door

        body = inspect.getsource(door.run_turn)
        for name in ("opening_express(", "closing_express("):
            at = body.index(name)
            window = body[at : at + 2200]
            assert "finish(" in window, (
                f"the {name.rstrip('(')} draw does not go through `finish`, so its controls "
                "open empty over a trip that knows the answer"
            )
