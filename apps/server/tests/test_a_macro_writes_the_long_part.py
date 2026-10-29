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
