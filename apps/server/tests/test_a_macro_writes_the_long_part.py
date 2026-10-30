"""`Itinerary()` — one line in, a day plan out.

The day plan is the largest thing this agent writes, and it used to write it
twice: once into `save_trip({days: […]})`, because a plan that lives only on a
card cannot be shared or edited and is gone next turn, and once again as
components because the card had to be drawn. The second copy is the same data
in a different notation — about seven hundred output tokens on a four-day
trip, which the traveller waits through at the end of the slowest turn in the
app.

So the catalog advertises a component no renderer ever receives. The model
writes `Itinerary()`; the host replaces that node with the days it already
holds, before the surface goes out.

What these tests hold down is the part that would fail quietly: that the
expansion really happens (a macro reaching a renderer is a blank box), that it
reads *this turn's* trip, and that what comes out is a flat adjacency list
rather than a nested tree — because a renderer draws `children` as ids, and a
tree of inline objects renders as nothing at all.
"""

from __future__ import annotations

from typing import Any

import pytest

from travel_a2ui.brain.catalog import (
    COMPONENT_NAMES,
    REQUIRED_PROPERTIES,
    VALIDATOR,
    parser_for,
)
from travel_a2ui.brain.express import ExpressStream, Failed, Ui
from travel_a2ui.brain.wire import components_of

SOURCE = 'plan = Itinerary("Four days in Berlin")\nroot = Column([plan])'

TRIP = {
    "days": [
        {
            "title": "Day 1 — Arrival",
            "date": "2026-10-12",
            "summary": "Settle in",
            "activities": [
                {"title": "Check in", "time": "14:00", "category": "stay"},
                {"title": "Walk the Ku'damm", "time": "15:30", "location": "Kurfürstendamm"},
            ],
        },
        {
            "title": "Day 2 — Mitte",
            "date": "2026-10-13",
            "activities": [{"title": "Museum Island", "time": "10:00"}],
        },
    ]
}


def drawn(source: str = SOURCE, trip: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every component a block puts on screen, after the host has expanded it."""
    stream = ExpressStream(
        parser=parser_for("inline-9"),
        components=COMPONENT_NAMES,
        validator=VALIDATOR,
        required=REQUIRED_PROPERTIES,
        trip=TRIP if trip is None else trip,
    )
    events = list(stream.feed(["<a2ui>" + source + "</a2ui>"]))
    refused = [event for event in events if isinstance(event, Failed)]
    assert not refused, refused[0].message if refused else ""
    return [
        node
        for event in events
        if isinstance(event, Ui)
        for message in event.messages
        for node in components_of(message)
    ]


def kinds(nodes: list[dict[str, Any]]) -> dict[str, int]:
    counted: dict[str, int] = {}
    for node in nodes:
        counted[str(node.get("component"))] = counted.get(str(node.get("component")), 0) + 1
    return counted


class TestItExpands:
    def test_one_line_becomes_the_whole_plan(self) -> None:
        counted = kinds(drawn())
        assert counted["ItineraryDay"] == 2, "one per day recorded"
        assert counted["ActivityItem"] == 3, "one per activity across those days"

    def test_the_macro_itself_never_reaches_the_renderer(self) -> None:
        """A component no renderer knows draws as nothing, silently."""
        assert "Itinerary" not in kinds(drawn())

    def test_the_heading_is_the_agents_own_words(self) -> None:
        headings = [n for n in drawn() if n["component"] == "Text"]
        assert [h["text"] for h in headings] == ["Four days in Berlin"]

    def test_and_is_left_out_when_the_agent_does_not_pass_one(self) -> None:
        nodes = drawn('plan = Itinerary()\nroot = Column([plan])')
        assert "Text" not in kinds(nodes)


class TestItReadsThisTurnsTrip:
    def test_the_activities_are_the_ones_recorded(self) -> None:
        titles = [n["title"] for n in drawn() if n["component"] == "ActivityItem"]
        assert titles == ["Check in", "Walk the Ku'damm", "Museum Island"]

    def test_the_fields_survive_the_round_trip(self) -> None:
        first = next(n for n in drawn() if n["component"] == "ActivityItem")
        assert first["time"] == "14:00"
        assert first["category"] == "stay"

    def test_a_trip_with_no_plan_says_so_rather_than_drawing_a_box(self) -> None:
        nodes = drawn(trip={})
        assert kinds(nodes).get("ItineraryDay") is None
        assert any("No day plan" in str(n.get("text", "")) for n in nodes)

    def test_two_turns_do_not_see_each_others_trips(self) -> None:
        """Turns run concurrently on one instance; the trip is per expansion."""
        other = {"days": [{"title": "Lisbon", "activities": [{"title": "Tram 28"}]}]}
        mine = [n["title"] for n in drawn() if n["component"] == "ActivityItem"]
        theirs = [n["title"] for n in drawn(trip=other) if n["component"] == "ActivityItem"]
        assert theirs == ["Tram 28"]
        assert mine[0] == "Check in"


class TestWhatTheRendererGets:
    def test_children_are_ids_rather_than_nested_objects(self) -> None:
        """A tree of inline objects compiles and renders as nothing."""
        nodes = drawn()
        day = next(n for n in nodes if n["component"] == "ItineraryDay")
        assert day["children"] and all(isinstance(child, str) for child in day["children"])

    def test_every_child_named_is_a_component_that_exists(self) -> None:
        nodes = drawn()
        ids = {node["id"] for node in nodes}
        for node in nodes:
            for child in node.get("children") or []:
                if isinstance(child, str):
                    assert child in ids, f"{node['id']} names a component that is not here"

    def test_an_activity_can_be_dropped_from_the_trip_it_came_from(self) -> None:
        """The edit goes back to the trip, not to the card it was drawn on."""
        nodes = drawn()
        events = [n["onRemove"]["event"] for n in nodes if n["component"] == "ActivityItem"]
        assert [event["name"] for event in events] == ["drop_activity"] * 3
        assert [event["context"] for event in events] == [
            {"day": 0, "index": 0},
            {"day": 0, "index": 1},
            {"day": 1, "index": 0},
        ]


class TestHighlightsIsBoundRatherThanLiteral:
    """The invariant the panel taught us, asserted on the other bound macro.

    `Trip()` was redrawn rather than bound for a while, and the cost was not a
    wrong pixel: the host filed a pressed fare at `/trip/selectedFlight` and a
    literal panel could not hear it, so the sidebar sat twenty seconds behind
    the traveller. `Highlights()` exists to go on screen *before* its rows
    arrive, which is only true if every field on it is a path.
    """

    def test_every_field_on_the_row_is_a_path(self) -> None:
        nodes = drawn("rows = Highlights()\nroot = Column([rows])", trip={})
        rows = [node for node in nodes if node.get("component") == "ActivityItem"]
        assert len(rows) == 1, "one template, however many highlights arrive"
        row = rows[0]
        for field in ("title", "note"):
            assert isinstance(row.get(field), dict), f"{field} is literal: {row.get(field)!r}"
            assert "@path" in row[field], row[field]

    def test_the_list_reads_the_address_the_host_files_to(self) -> None:
        from travel_a2ui.brain.macros import HIGHLIGHTS, LANDINGS

        nodes = drawn("rows = Highlights()\nroot = Column([rows])", trip={})
        lists = [node for node in nodes if node.get("component") == "List"]
        assert len(lists) == 1
        children = lists[0]["children"]
        assert children["path"] == HIGHLIGHTS
        assert LANDINGS["get_destination"][0] == HIGHLIGHTS, "the two sides of one address"

    def test_it_draws_against_an_empty_trip(self) -> None:
        """Which is the point: it goes up before the lookup has returned.

        `Itinerary()` reads the trip and says "no day plan recorded yet" when
        there is none, because its data is the agent's own writing. This one's
        data arrives as rows, so an empty trip is not an empty card — it is a
        card waiting, and that is the whole reason it can be drawn first.
        """
        nodes = drawn("rows = Highlights()\nroot = Column([rows])", trip={})
        assert kinds(nodes).get("ActivityItem") == 1
        assert "No day plan recorded yet." not in str(nodes)

    def test_a_heading_is_drawn_and_the_rest_is_not(self) -> None:
        nodes = drawn('rows = Highlights("Worth your time")\nroot = Column([rows])', trip={})
        texts = [node for node in nodes if node.get("component") == "Text"]
        assert [node.get("text") for node in texts] == ["Worth your time"]


SETTLED = {
    "destination": "Berlin",
    "origin": "CPH",
    "startDate": "2026-11-02",
    "endDate": "2026-11-05",
    "travelers": 2,
    "needsStay": True,
    "selectedFlight": "SK8495",
    "flightPrice": 69,
    "airline": "SAS",
    "departTime": "07:15",
    "arriveTime": "08:25",
    "selectedHotel": "h_BER_savigny",
    "hotelName": "Pension Savignyplatz",
    "nightlyPrice": 112,
}


class TestThePanelBindsToWhatTheTripActuallyHolds:
    """The bug that read as "the cards never finish loading".

    `Trip()` bound `FlightOption.airline` to `/trip/airline`, and the trip had
    no such key — `TRIP_KEYS` held `selectedFlight` and `flightPrice` and
    nothing about what the flight *was*. The renderer's rule is that a path
    which does not resolve is pending, so every field but the price drew as a
    shimmer, for ever, because nothing was ever going to send it.

    So this is not a test about spelling. Every path this panel binds has to be
    a key the trip can hold, or the panel is a loading state with no load
    behind it.
    """

    def panel(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        return drawn('panel = Trip("Your trip")\nroot = Column([panel])', trip=record)

    def test_every_bound_path_names_a_key_the_trip_can_hold(self) -> None:
        from travel_a2ui.brain.trip.fields import TRIP_KEYS

        nodes = self.panel(SETTLED)
        paths: list[str] = []
        for node in nodes:
            for value in node.values():
                if isinstance(value, dict) and "@path" in value:
                    paths.append(value["@path"])
        assert paths, "the panel binds nothing at all"
        for path in paths:
            assert path.startswith("/trip/"), path
            # `legs/0/selectedFlight` addresses a leg; the field after the last
            # slash is the one that has to exist.
            key = path[len("/trip/") :].rsplit("/", 1)[-1]
            assert key in TRIP_KEYS, f"{path} names {key!r}, which no trip has"

    def test_the_stay_shows_its_name_rather_than_its_id(self) -> None:
        stays = [n for n in self.panel(SETTLED) if n.get("component") == "HotelCard"]
        assert len(stays) == 1
        assert stays[0]["name"] == {"@path": "/trip/hotelName"}
        assert stays[0]["selected"] == {"@path": "/trip/selectedHotel"}, "the id still marks it"


class TestThePanelDrawsOnlyWhatIsSettled:
    def panel(self, record: dict[str, Any]) -> dict[str, int]:
        return kinds(drawn('panel = Trip("Your trip")\nroot = Column([panel])', trip=record))

    def test_a_trip_with_no_fare_draws_no_fare(self) -> None:
        """What a traveller used to see was two cards shimmering at nothing."""
        without = {k: v for k, v in SETTLED.items() if k != "selectedFlight"}
        assert self.panel(without).get("FlightOption") is None

    def test_a_hop_that_stays_the_night_with_no_hotel_draws_no_hotel(self) -> None:
        """The condition used to be `nights`, which every stay-over hop has."""
        without = {k: v for k, v in SETTLED.items() if k != "selectedHotel"}
        assert without["needsStay"] is True
        assert self.panel(without).get("HotelCard") is None

    def test_and_both_appear_once_both_are_chosen(self) -> None:
        counted = self.panel(SETTLED)
        assert counted.get("FlightOption") == 1
        assert counted.get("HotelCard") == 1

    def test_a_second_hop_gets_its_own_fare_row(self) -> None:
        two = {**SETTLED, "legs": [{"destination": "Copenhagen", "selectedFlight": "SK2916"}]}
        assert self.panel(two).get("FlightOption") == 2

    def test_but_not_a_stay_row_it_has_not_chosen(self) -> None:
        two = {**SETTLED, "legs": [{"destination": "Copenhagen", "selectedFlight": "SK2916"}]}
        assert self.panel(two).get("HotelCard") == 1, "the first hop's, and only that"

    def test_an_empty_trip_still_draws_something_to_look_at(self) -> None:
        assert "Text" in self.panel({})


AIRPORTS = {
    "from": [{"value": "CPH", "label": "Copenhagen · CPH"}, {"value": "JFK", "label": "New York · JFK"}],
    "to": [{"value": "Berlin", "label": "Berlin · BER"}, {"value": "Madrid", "label": "Madrid · MAD"}],
}


def asked(record: dict[str, Any], airports: dict[str, Any] | None = AIRPORTS) -> list[dict[str, Any]]:
    """`Ask()` expanded, with this deployment's airports in scope."""
    from travel_a2ui.brain.express import as_wire
    from travel_a2ui.brain.macros import expand

    source = 'form = Ask("What is still missing?")\nroot = Column([form])'
    wire = as_wire(
        expand(parser_for("inline-1").compile(source, is_final=True), record, airports)
    )
    return wire[0]["createSurface"]["components"]


class TestAskHasSomewhereToSayWhereFrom:
    """The control that went missing when `Ask()` became the opening surface.

    The macro drew dates and traveller counters and nothing else, while its own
    docstring promised "where they are flying from" and the brief told the
    agent to draw a picker of airports. So the one turn where nothing is known
    offered no way to say the two things it most needs.
    """

    def pickers(self, record: dict[str, Any], **kw: Any) -> dict[str, dict[str, Any]]:
        found = {}
        for node in asked(record, **kw):
            if node.get("component") == "ChoicePicker":
                found[str(node.get("label"))] = node
        return found

    def test_an_empty_trip_is_asked_both(self) -> None:
        assert set(self.pickers({})) == {"Where to", "Flying from"}

    def test_each_writes_to_its_own_field(self) -> None:
        pickers = self.pickers({})
        assert pickers["Where to"]["value"] == {"@path": "/trip/destination"}
        assert pickers["Flying from"]["value"] == {"@path": "/trip/origin"}

    def test_one_at_a_time_rather_than_a_set(self) -> None:
        """`mutuallyExclusive`, so the renderer writes the value, not `[value]`."""
        for picker in self.pickers({}).values():
            assert picker["variant"] == "mutuallyExclusive"

    def test_what_is_known_is_not_asked_again(self) -> None:
        assert set(self.pickers({"destination": "Berlin"})) == {"Flying from"}
        assert set(self.pickers({"origin": "CPH"})) == {"Where to"}
        assert self.pickers({"destination": "Berlin", "origin": "CPH"}) == {}

    def test_the_button_carries_both_paths(self) -> None:
        """A control whose value never reaches the trip is a form nobody can submit."""
        buttons = [n for n in asked({}) if n.get("component") == "Button"]
        assert len(buttons) == 1
        paths = buttons[0]["action"]["event"]["context"]["paths"]
        assert "/trip/destination" in paths
        assert "/trip/origin" in paths

    def test_with_no_airport_list_it_asks_nothing_it_cannot_offer(self) -> None:
        """A picker with no options is a question with no answers on it.

        `ChoicePicker.options` is static in the schema, so when the host has no
        list — a provider whose catalogue call failed — there is nothing to draw
        and the agent's own question is what gets asked.
        """
        assert self.pickers({}, airports={}) == {}
        assert self.pickers({}, airports=None) == {}

    def test_a_long_list_is_searchable_and_a_short_one_is_not(self) -> None:
        many = {"from": [{"value": f"A{n}", "label": f"A{n}"} for n in range(12)], "to": []}
        assert self.pickers({"destination": "Berlin"}, airports=many)["Flying from"]["filterable"] is True
        few = {"from": AIRPORTS["from"], "to": []}
        assert self.pickers({"destination": "Berlin"}, airports=few)["Flying from"]["filterable"] is False


class TestWhatTheOptionsStore:
    def test_an_origin_stores_its_code_because_the_field_is_a_code(self) -> None:
        from travel_a2ui.brain.macros import airport_choices

        made = airport_choices([{"code": "CPH", "city": "Copenhagen"}], [])
        assert made["from"] == [{"value": "CPH", "label": "Copenhagen · CPH"}]

    def test_a_destination_stores_its_city_because_the_panel_reads_it(self) -> None:
        """A trip stored as "→ MAD" says MAD everywhere a person expects Madrid."""
        from travel_a2ui.brain.macros import airport_choices

        made = airport_choices([], [{"city": "Madrid", "airport": "MAD"}])
        assert made["to"] == [{"value": "Madrid", "label": "Madrid · MAD"}]

    def test_both_labels_name_the_city_and_the_code(self) -> None:
        from travel_a2ui.brain.macros import airport_choices

        made = airport_choices([{"code": "CPH", "city": "Copenhagen"}], [{"city": "Berlin", "airport": "BER"}])
        assert made["from"][0]["label"] == "Copenhagen · CPH"
        assert made["to"][0]["label"] == "Berlin · BER"

    def test_a_row_with_nothing_usable_is_dropped(self) -> None:
        from travel_a2ui.brain.macros import airport_choices

        made = airport_choices([{"city": "Nowhere"}, "not a dict", {}], [{}, {"airport": ""}])
        assert made == {"from": [], "to": []}


class TestAHopHoweverTheModelSpellsIt:
    """The signature says `int` and nothing enforces it.

    `Flights("Back · MAD → JFK", "", "2")` is a thing the model writes, and it
    raised `'>' not supported between instances of 'str' and 'int'` inside the
    expander. The expander catches that and reports "Failed to expand macro
    'Flights'", so the entire fare list did not draw — the traveller got prose
    about four flights and no cards, and the only trace was one line in a log.
    Found by the journey validator, which then crashed on the consequence.
    """

    def context(self, hop: str) -> dict[str, Any]:
        source = f"rows = Flights(\"Back\", \"\", {hop})\nroot = Column([rows])"
        fares = [n for n in drawn(source, trip={}) if n.get("component") == "FlightOption"]
        assert len(fares) == 1, f"the list did not draw for hop={hop}"
        return fares[0]["action"]["event"]["context"]

    @pytest.mark.parametrize("written", ['"2"', "2", "2.0", '"2.0"'])
    def test_every_spelling_of_hop_two_draws_and_names_the_hop(self, written: str) -> None:
        assert self.context(written)["hop"] == 2

    @pytest.mark.parametrize("written", ['""', '"two"', "0", "1"])
    def test_and_a_hop_that_is_not_a_later_one_draws_without_naming_it(self, written: str) -> None:
        """Hop one is the trip's own fields; saying so would look for `legs[-1]`."""
        assert "hop" not in self.context(written)

    def test_the_list_still_draws_when_the_hop_makes_no_sense(self) -> None:
        """Losing the hop is bad. Losing the whole card is worse."""
        assert self.context('"later"') == self.context('""')
