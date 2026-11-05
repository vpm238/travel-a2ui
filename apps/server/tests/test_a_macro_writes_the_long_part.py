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
        assert [h["text"] for h in headings] == ["### Four days in Berlin"]

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
        assert [node.get("text") for node in texts] == ["### Worth your time"]


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
        # Drawn only once a stay is chosen, so it is the chosen one. It was bound
        # to the id — a string in a boolean slot, which marked nothing.
        assert stays[0]["selected"] is True

    def test_a_list_marks_the_row_the_trip_chose(self) -> None:
        nodes = drawn('fares = Flights("Outbound", "/trip/selectedFlight")\nroot = Column([fares])')
        row = next(n for n in nodes if n.get("component") == "FlightOption")
        assert row["selected"] == {
            "@call": "equals",
            "args": {"a": {"@path": "id"}, "b": {"@path": "/trip/selectedFlight"}},
        }


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
    "from": [
        {"value": "CPH", "label": "Copenhagen", "code": "CPH", "detail": "Europe"},
        {"value": "JFK", "label": "New York", "code": "JFK", "detail": "North America"},
    ],
    "to": [
        {"value": "Berlin", "label": "Berlin", "code": "BER", "detail": "Germany"},
        {"value": "Madrid", "label": "Madrid", "code": "MAD", "detail": "Spain"},
    ],
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
            if node.get("component") == "AirportPicker":
                found[str(node.get("label"))] = node
        return found

    def test_an_empty_trip_is_asked_both(self) -> None:
        assert set(self.pickers({})) == {"Where to?", "Where from?"}

    def test_each_writes_to_its_own_field(self) -> None:
        pickers = self.pickers({})
        assert pickers["Where to?"]["value"] == {"@path": "/trip/destination"}
        assert pickers["Where from?"]["value"] == {"@path": "/trip/origin"}

    def test_a_search_field_not_a_list_of_radio_buttons(self) -> None:
        """An `AirportPicker`, whose `kind` sets the end of the trip it asks for."""
        pickers = self.pickers({})
        assert pickers["Where from?"]["kind"] == "origin"
        assert pickers["Where to?"]["kind"] == "destination"
        assert all(picker["options"] for picker in pickers.values())

    def test_what_is_known_is_not_asked_again(self) -> None:
        assert set(self.pickers({"destination": "Berlin"})) == {"Where from?"}
        assert set(self.pickers({"origin": "CPH"})) == {"Where to?"}
        assert self.pickers({"destination": "Berlin", "origin": "CPH"}) == {}

    def test_one_button_sends_both_answers(self) -> None:
        """A control whose value never reaches the trip is a form nobody can submit.

        The answers travel as the surface's data model (`sendDataModel`), so the
        button needs only to exist, on the surface whose editors hold them.
        """
        nodes = asked({})
        buttons = [n for n in nodes if n.get("component") == "Button"]
        assert len(buttons) == 1
        assert buttons[0]["action"]["event"]["name"] == "commit_surface"
        bound = {n["value"]["@path"] for n in nodes if isinstance(n.get("value"), dict) and "@path" in n["value"]}
        assert {"/trip/destination", "/trip/origin"} <= bound

    def test_with_no_airport_list_it_asks_nothing_it_cannot_offer(self) -> None:
        """A picker with no options is a question with no answers on it.

        `ChoicePicker.options` is static in the schema, so when the host has no
        list — a provider whose catalogue call failed — there is nothing to draw
        and the agent's own question is what gets asked.
        """
        assert self.pickers({}, airports={}) == {}
        assert self.pickers({}, airports=None) == {}

class TestWhatTheOptionsStore:
    def test_an_origin_stores_its_code_because_the_field_is_a_code(self) -> None:
        from travel_a2ui.brain.macros import airport_choices

        made = airport_choices([{"code": "CPH", "city": "Copenhagen"}], [])
        assert made["from"] == [{"value": "CPH", "label": "Copenhagen", "code": "CPH"}]

    def test_a_destination_stores_its_city_because_the_panel_reads_it(self) -> None:
        """A trip stored as "→ MAD" says MAD everywhere a person expects Madrid."""
        from travel_a2ui.brain.macros import airport_choices

        made = airport_choices([], [{"city": "Madrid", "airport": "MAD"}])
        assert made["to"] == [{"value": "Madrid", "label": "Madrid", "code": "MAD"}]

    def test_each_names_the_city_the_code_and_where_it_is(self) -> None:
        from travel_a2ui.brain.macros import airport_choices

        made = airport_choices(
            [{"code": "CPH", "city": "Copenhagen", "region": "europe"}],
            [{"city": "Berlin", "airport": "BER", "country": "Germany"}],
        )
        assert made["from"][0] == {"value": "CPH", "label": "Copenhagen", "code": "CPH", "detail": "Europe"}
        assert made["to"][0] == {"value": "Berlin", "label": "Berlin", "code": "BER", "detail": "Germany"}

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


class TestThePanelShowsMoneyAsMoney:
    """`69` is not a price, and the fare list beside it said `€69`.

    A `money` field is kept as a number because a total is arithmetic; the
    provider quotes a display string. Bound straight in, the panel therefore
    rendered the number — a trip whose cards had finally filled in still read
    "SAS SK8495 … 69". `formatCurrency` is in the catalog and the renderer
    implements it, so the panel formats what it has rather than the app keeping
    a second, pre-formatted copy that something has to hold in step.
    """

    SETTLED = {
        "destination": "Berlin",
        "origin": "CPH",
        "selectedFlight": "SK8495",
        "flightPrice": 69,
        "needsStay": True,
        "selectedHotel": "h1",
        "hotelName": "Pension Savignyplatz",
        "nightlyPrice": 112,
    }

    def panel(self, currency: str = "EUR") -> list[dict[str, Any]]:
        from travel_a2ui.brain.express import as_wire
        from travel_a2ui.brain.macros import expand

        source = 'panel = Trip("Your trip")\nroot = Column([panel])'
        wire = as_wire(
            expand(parser_for("sidebar").compile(source, is_final=True), self.SETTLED, {}, currency)
        )
        return wire[0]["createSurface"]["components"]

    def test_a_fare_is_drawn_through_format_currency(self) -> None:
        fare = next(n for n in self.panel() if n["component"] == "FlightOption")
        assert fare["price"]["@call"] == "formatCurrency"
        assert fare["price"]["args"]["value"] == {"@path": "/trip/flightPrice"}
        assert fare["price"]["args"]["currency"] == "EUR"

    def test_and_so_is_a_stay(self) -> None:
        stay = next(n for n in self.panel() if n["component"] == "HotelCard")
        assert stay["price"]["@call"] == "formatCurrency"
        assert stay["price"]["args"]["value"] == {"@path": "/trip/nightlyPrice"}

    def test_the_code_follows_the_turn(self) -> None:
        fare = next(n for n in self.panel("JPY") if n["component"] == "FlightOption")
        assert fare["price"]["args"]["currency"] == "JPY"

    def test_the_amount_is_still_bound_rather_than_written_in(self) -> None:
        """A price the host wrote out is a price that cannot change."""
        import json

        drawn = json.dumps(self.panel())
        assert '"69"' not in drawn and ": 69" not in drawn


class TestWhichCurrencyATripIsIn:
    def rows(self) -> list[dict[str, Any]]:
        return [
            {"city": "Berlin", "airport": "BER", "currency": "EUR"},
            {"city": "Tokyo", "airport": "HND", "currency": "JPY"},
        ]

    def test_by_city_or_by_airport(self) -> None:
        from travel_a2ui.brain.macros import currency_for

        assert currency_for(self.rows(), {"destination": "Berlin"}) == "EUR"
        assert currency_for(self.rows(), {"destination": "BER"}) == "EUR"
        assert currency_for(self.rows(), {"destination": "tokyo"}) == "JPY"

    def test_dollars_when_nothing_is_settled(self) -> None:
        from travel_a2ui.brain.macros import currency_for

        assert currency_for(self.rows(), {}) == "USD"
        assert currency_for(self.rows(), {"destination": "Atlantis"}) == "USD"
        assert currency_for([], {"destination": "Berlin"}) == "USD"

    def test_the_trips_destination_and_not_the_hop_being_priced(self) -> None:
        """The subtlety `_trip_currency` documents, held here too.

        Pricing the way home calls `search_flights` with `destination: "CPH"`.
        A currency read off *that* comes back as kroner for the return of a
        Berlin trip whose outbound and hotel are both in euros.
        """
        from travel_a2ui.brain.macros import currency_for

        berlin_trip = {"destination": "Berlin", "legs": [{"destination": "Copenhagen"}]}
        assert currency_for(self.rows(), berlin_trip) == "EUR"


class TestWhichHopAFareListIsFor:
    """The hop reaches the press from the path when the number is omitted.

    `Flights(…, selected="/trip/legs/0/selectedFlight")` is a list of fares for
    hop two whether or not `hop=2` was also passed — and measured, the agent
    passes the path and omits the number. A whole browser walkthrough recorded
    `"hop": 2` zero times while binding `selected` to a leg every time.

    That matters beyond tidiness: without the hop the press lands saying
    nothing about which leg it settled, so the sentence telling the agent to
    put the airline and the times on `legs[0]` never fires. The fix for that
    was right and simply never reached.
    """

    def context(self, source: str) -> dict[str, Any]:
        node = next(
            n for n in drawn(source, trip={}) if n.get("component") in ("FlightOption", "HotelCard")
        )
        return node["action"]["event"]["context"]

    def test_a_leg_path_is_enough(self) -> None:
        got = self.context(
            'rows = Flights("Back", "/trip/legs/0/selectedFlight")\nroot = Column([rows])'
        )
        assert got["hop"] == 2

    def test_a_later_leg_too(self) -> None:
        got = self.context(
            'rows = Flights("Third", "/trip/legs/1/selectedFlight")\nroot = Column([rows])'
        )
        assert got["hop"] == 3

    def test_a_stay_list_reads_it_the_same_way(self) -> None:
        got = self.context(
            'rows = Stays("Stops", "/trip/legs/0/selectedHotel")\nroot = Column([rows])'
        )
        assert got["hop"] == 2

    def test_the_trips_own_path_is_hop_one_and_says_nothing(self) -> None:
        """Hop one is the trip's own fields; naming it sends the press to `legs[-1]`."""
        got = self.context(
            'rows = Flights("Out", "/trip/selectedFlight")\nroot = Column([rows])'
        )
        assert "hop" not in got

    def test_an_explicit_hop_still_wins(self) -> None:
        got = self.context(
            'rows = Flights("Back", "/trip/legs/0/selectedFlight", 2)\nroot = Column([rows])'
        )
        assert got["hop"] == 2

    def test_and_no_selected_path_at_all_is_still_a_list(self) -> None:
        got = self.context('rows = Flights("Fares")\nroot = Column([rows])')
        assert "hop" not in got
