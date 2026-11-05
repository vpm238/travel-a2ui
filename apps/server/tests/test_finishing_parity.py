"""The four passes the server makes over a surface, held to the TypeScript.

These are the passes that keep a thin client thin: the Flutter client
gets a surface that is already correct and gains no logic to make it so. Which
is exactly why both servers have to make them identically — and why the
failures here are all quiet ones. A port that seeds `/trip` but forgets `/plan`
ships a panel that renders blank before anything is decided. One that binds
commit contexts in a different order ships buttons whose payload keys change
between turns. One that strips the wrong `change` button leaves two of them on
screen for the same decision. Nothing throws in any of those cases.
"""

from __future__ import annotations

import copy
import json
import pathlib

import pytest

from travel_a2ui.brain.catalog import PROTOCOL_VERSION
from travel_a2ui.brain.finishing import (
    STANDING_SURFACES,
    ensure_commit_button,
    finish,
    plan_rows,
    seed_surface_trip,
    strip_panel_actions,
    trip_updates,
)

ROOT = pathlib.Path(__file__).resolve().parents[3]
GOLDEN = json.loads(
    (ROOT / "tools" / "parity" / "__golden__" / "finishing.json").read_text("utf-8")
)

TRIPS: dict[str, dict] = {
    "empty": {},
    "started": {"destination": "Madrid"},
    "ready": {
        "origin": "JFK",
        "destination": "Madrid",
        "startDate": "2027-04-12",
        "endDate": "2027-04-19",
        "travelers": 2,
    },
    "skipping": {"destination": "Madrid", "origin": "JFK", "skip": ["stay", "budget"]},
    "multiCity": {
        "origin": "SFO",
        "destination": "Chicago",
        "startDate": "2027-04-12",
        "endDate": "2027-04-14",
        "travelers": 1,
        "legs": [
            {
                "destination": "New York",
                "startDate": "2027-04-14",
                "endDate": "2027-04-18",
                "purpose": "a wedding",
            },
            {
                "destination": "San Francisco",
                "startDate": "2027-04-18",
                "travelers": 2,
                "needsStay": False,
            },
        ],
    },
}


def _surface(surface_id: str, components: list, data_model: dict | None = None) -> list:
    created: dict = {"surfaceId": surface_id, "catalogId": "travel"}
    if data_model:
        created["dataModel"] = data_model
    return [
        {"version": PROTOCOL_VERSION, "createSurface": created},
        {"version": PROTOCOL_VERSION, "updateComponents": {"surfaceId": surface_id, "components": components}},
    ]


#: The same surfaces the capture script built, each chosen for one pass.
SURFACES = {
    "editors with a button that binds nothing": lambda: _surface(
        "inline-1",
        [
            {"id": "from", "component": "TextField", "label": "From", "text": {"@path": "/trip/origin"}},
            {
                "id": "when",
                "component": "DateRangePicker",
                "label": "Dates",
                "start": {"@path": "/trip/startDate"},
                "end": {"@path": "/trip/endDate"},
            },
            {"id": "who", "component": "TravelerCounter", "label": "Travelers", "value": {"@path": "/trip/travelers"}},
            {"id": "go", "component": "Button", "label": "Search", "action": {"event": {"name": "search_flights", "context": {}}}},
            {"id": "root", "component": "Column", "children": ["from", "when", "who", "go"]},
        ],
    ),
    "a button that already bound one thing itself": lambda: _surface(
        "inline-1",
        [
            {"id": "from", "component": "TextField", "label": "From", "text": {"@path": "/trip/origin"}},
            {"id": "who", "component": "TravelerCounter", "label": "Travelers", "value": {"@path": "/trip/travelers"}},
            {
                "id": "go",
                "component": "Button",
                "label": "Search",
                "action": {"event": {"name": "search_flights", "context": {"departingFrom": {"@path": "/trip/origin"}}}},
            },
            {"id": "root", "component": "Column", "children": ["from", "who", "go"]},
        ],
    ),
    "editors and no button at all, which is a dead end": lambda: _surface(
        "inline-1",
        [
            {"id": "from", "component": "TextField", "label": "From", "text": {"@path": "/trip/origin"}},
            {"id": "who", "component": "TravelerCounter", "label": "Travelers", "value": {"@path": "/trip/travelers"}},
            {"id": "root", "component": "Column", "children": ["from", "who"]},
        ],
    ),
    "two buttons, both of which must carry the answer": lambda: _surface(
        "inline-1",
        [
            {
                "id": "when",
                "component": "DateRangePicker",
                "label": "Dates",
                "start": {"@path": "/trip/startDate"},
                "end": {"@path": "/trip/endDate"},
            },
            {"id": "a", "component": "Button", "label": "Search flights", "action": {"event": {"name": "search_flights", "context": {}}}},
            {"id": "b", "component": "Button", "label": "Search hotels", "action": {"event": {"name": "search_hotels", "context": {}}}},
            {"id": "root", "component": "Column", "children": ["when", "a", "b"]},
        ],
    ),
    "colliding key names from two different paths": lambda: _surface(
        "inline-1",
        [
            {"id": "a", "component": "TextField", "label": "From", "text": {"@path": "/trip/origin"}},
            {"id": "b", "component": "TextField", "label": "Leg from", "text": {"@path": "/leg/origin"}},
            {"id": "go", "component": "Button", "label": "Go", "action": {"event": {"name": "go", "context": {}}}},
            {"id": "root", "component": "Column", "children": ["a", "b", "go"]},
        ],
    ),
    "a night count written as literal text": lambda: _surface(
        "inline-1",
        [
            {
                "id": "when",
                "component": "DateRangePicker",
                "label": "Dates",
                "start": {"@path": "/trip/startDate"},
                "end": {"@path": "/trip/endDate"},
                "nightsLabel": "7 nights",
            },
            {"id": "root", "component": "Column", "children": ["when"]},
        ],
    ),
    "a night count the model already wrote as a template": lambda: _surface(
        "inline-1",
        [
            {
                "id": "when",
                "component": "DateRangePicker",
                "label": "Dates",
                "start": {"@path": "/trip/startDate"},
                "end": {"@path": "/trip/endDate"},
                "nightsLabel": {
                    "call": "formatString",
                    "args": {
                        "value": "${calcNights(start:${/trip/startDate}, end:${/trip/endDate})} nights, including the wedding"
                    },
                },
            },
            {"id": "root", "component": "Column", "children": ["when"]},
        ],
    ),
    "a picker whose ends are literal dates": lambda: _surface(
        "inline-1",
        [
            {
                "id": "when",
                "component": "DateRangePicker",
                "label": "Dates",
                "start": "2027-04-12",
                "end": "2027-04-19",
                "nightsLabel": "7 nights",
            },
            {"id": "root", "component": "Column", "children": ["when"]},
        ],
    ),
    "a change button drawn inline, where it does not belong": lambda: _surface(
        "inline-1",
        [
            {"id": "ask", "component": "Text", "text": "When are you going?"},
            {"id": "label", "component": "Text", "text": "Route"},
            {"id": "change", "component": "Button", "label": "Change", "action": {"event": {"name": "change", "context": {"field": "destination"}}}},
            {"id": "recap", "component": "Row", "children": ["label", "change"]},
            {"id": "root", "component": "Column", "children": ["ask", "recap"]},
        ],
    ),
    "a change button alone in a row, which leaves the row empty": lambda: _surface(
        "inline-1",
        [
            {"id": "ask", "component": "Text", "text": "When are you going?"},
            {"id": "change", "component": "Button", "label": "Change", "action": {"event": {"name": "change", "context": {"field": "destination"}}}},
            {"id": "onlyChange", "component": "Row", "children": ["change"]},
            {"id": "root", "component": "Column", "children": ["ask", "onlyChange"]},
        ],
    ),
    "the same change button on the panel, where it does": lambda: _surface(
        "sidebar",
        [
            {"id": "label", "component": "Text", "text": "Route"},
            {"id": "change", "component": "Button", "label": "Change", "action": {"event": {"name": "change", "context": {"field": "destination"}}}},
            {"id": "root", "component": "Column", "children": ["label", "change"]},
        ],
    ),
    "a surface that already seeded a value itself": lambda: _surface(
        "inline-1",
        [
            {
                "id": "when",
                "component": "DateRangePicker",
                "label": "Dates",
                "start": {"@path": "/trip/startDate"},
                "end": {"@path": "/trip/endDate"},
            },
            {"id": "root", "component": "Column", "children": ["when"]},
        ],
        {"trip": {"startDate": "2027-06-01"}},
    ),
    "a template row, whose path is a collection and not an answer": lambda: _surface(
        "inline-1",
        [
            {"id": "row", "component": "Text", "text": {"@path": "name"}},
            {"id": "list", "component": "List", "children": {"path": "/hotels", "componentId": "row"}},
            {"id": "pick", "component": "TextField", "label": "Note", "text": {"@path": "/trip/neighborhood"}},
            {"id": "go", "component": "Button", "label": "Go", "action": {"event": {"name": "go", "context": {}}}},
            {"id": "root", "component": "Column", "children": ["list", "pick", "go"]},
        ],
    ),
}


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2)


@pytest.mark.parametrize("name", list(GOLDEN["planRows"]))
def test_plan_rows_match(name: str) -> None:
    assert canonical(plan_rows(TRIPS[name])) == canonical(GOLDEN["planRows"][name])


@pytest.mark.parametrize("name", list(GOLDEN["tripUpdates"]))
def test_trip_updates_match(name: str) -> None:
    assert canonical(trip_updates("sidebar", TRIPS[name])) == canonical(
        GOLDEN["tripUpdates"][name]
    )


@pytest.mark.parametrize("name", list(GOLDEN["surfaces"]))
def test_the_whole_pipeline_matches(name: str) -> None:
    actual = finish(SURFACES[name](), TRIPS["ready"], STANDING_SURFACES)
    assert canonical(actual) == canonical(GOLDEN["surfaces"][name])


def test_the_golden_covers_every_surface_case() -> None:
    """Neither table may grow without the other."""
    assert set(SURFACES) == set(GOLDEN["surfaces"])


class TestWhatThePassesAreFor:
    """Stated directly, because a golden says what happened and not why."""

    def test_a_dead_end_gets_a_button(self) -> None:
        result = GOLDEN["surfaces"]["editors and no button at all, which is a dead end"]
        components = result[1]["updateComponents"]["components"]
        commit = next(node for node in components if node["id"] == "__commit")
        assert commit["action"]["event"]["name"] == "commit_surface"
        root = next(node for node in components if node["id"] == "root")
        assert "__commit" in root["children"]
        # And the answer goes with it: the surface asks for its data model back.
        assert result[0]["createSurface"]["sendDataModel"] is True

    def test_a_button_the_agent_wrote_is_left_as_it_wrote_it(self) -> None:
        """Nothing is added to an action's context: the data model carries the values.

        The host used to write every editable path into the button's context,
        and had to be taught not to mistake a template's collection (`/hotels`)
        for an answer, and not to rename a key the model chose. Neither question
        exists now.
        """
        for name in (
            "a button that already bound one thing itself",
            "a template row, whose path is a collection and not an answer",
        ):
            before = next(
                n
                for m in SURFACES[name]()
                if "updateComponents" in m
                for n in m["updateComponents"]["components"]
                if n["id"] == "go"
            )
            after = next(
                n
                for m in GOLDEN["surfaces"][name]
                if "updateComponents" in m
                for n in m["updateComponents"]["components"]
                if n["id"] == "go"
            )
            assert after["action"] == before["action"], name

    def test_a_literal_night_count_becomes_a_live_one(self) -> None:
        result = GOLDEN["surfaces"]["a night count written as literal text"]
        node = next(
            n
            for n in result[1]["updateComponents"]["components"]
            if n["id"] == "when"
        )
        # `@call`, the 1.0 key. This asserted `call` — the bug itself, written
        # down as the expected answer — so the test that existed to describe
        # the pass also guaranteed it stayed invalid.
        assert node["nightsLabel"]["@call"] == "formatString"
        assert "call" not in node["nightsLabel"]
        assert "calcNights" in node["nightsLabel"]["args"]["value"]

    def test_wording_the_model_chose_is_left_alone(self) -> None:
        result = GOLDEN["surfaces"]["a night count the model already wrote as a template"]
        node = next(n for n in result[1]["updateComponents"]["components"] if n["id"] == "when")
        assert "including the wedding" in node["nightsLabel"]["args"]["value"]

    def test_a_change_button_inline_is_removed(self) -> None:
        result = GOLDEN["surfaces"]["a change button drawn inline, where it does not belong"]
        components = result[1]["updateComponents"]["components"]
        ids = {node["id"] for node in components}
        assert "change" not in ids
        assert "ask" in ids, "and nothing else is"
        # The row survives, because it still holds the label. Only a container
        # left with nothing in it is a gap on screen that nothing explains.
        recap = next(node for node in components if node["id"] == "recap")
        assert recap["children"] == ["label"]

    def test_a_row_left_holding_nothing_goes_too(self) -> None:
        result = GOLDEN["surfaces"]["a change button alone in a row, which leaves the row empty"]
        components = result[1]["updateComponents"]["components"]
        ids = {node["id"] for node in components}
        assert "change" not in ids
        assert "onlyChange" not in ids, "an empty row is a gap nothing explains"
        # And the dangling reference goes with it, or the renderer looks up an
        # id that is no longer there.
        root = next(node for node in components if node["id"] == "root")
        assert root["children"] == ["ask"]

    def test_the_same_button_on_the_panel_stays(self) -> None:
        result = GOLDEN["surfaces"]["the same change button on the panel, where it does"]
        ids = {node["id"] for node in result[1]["updateComponents"]["components"]}
        assert "change" in ids

    def test_a_value_the_model_proposed_beats_the_saved_one(self) -> None:
        result = GOLDEN["surfaces"]["a surface that already seeded a value itself"]
        seeded = result[0]["createSurface"]["dataModel"]["trip"]
        # The trip says 2027-04-12; the surface proposed June. A proposal should
        # beat the older fact it proposes to replace.
        assert seeded["startDate"] == "2027-06-01"
        assert seeded["origin"] == "JFK", "and everything unproposed still arrives"

    def test_the_panel_is_seeded_even_when_nothing_is_decided(self) -> None:
        """A panel drawn before anything is decided must not render blank."""
        messages = seed_surface_trip(_surface("sidebar", []), {})
        data_model = messages[0]["createSurface"]["dataModel"]
        assert data_model["trip"] == {}
        assert data_model["plan"] == {
            "decisions": [],
            "route": [],
            "caption": "0 decided",
            "complete": False,
            "multiStop": False,
        }, "empty, but every key the panel binds to is there"


class TestPlanRowsReadCorrectly:
    def test_every_decision_is_a_row_the_traveler_can_change(self) -> None:
        """The panel is the record of what they said, one line each."""
        rows = plan_rows(TRIPS["ready"])
        keys = [row["key"] for row in rows["decisions"]]
        assert "destination" in keys and "startDate" in keys
        assert all(row["value"] and row["line"] for row in rows["decisions"])

    def test_a_hop_says_what_it_is_still_waiting_on(self) -> None:
        rows = plan_rows(TRIPS["ready"])
        assert rows["route"], "a trip with a destination has a route"
        assert any("stay" in row["detail"] or "ticket" in row["detail"] for row in rows["route"])

    def test_a_multi_stop_route_names_each_stop(self) -> None:
        rows = plan_rows(TRIPS["multiCity"])
        assert rows["multiStop"] is True
        assert [stop["place"] for stop in rows["route"]] == [
            "Chicago",
            "New York",
            "San Francisco",
        ]
        # The party size is only worth showing where it actually varies.
        assert "2×" in rows["route"][2]["line"]

    def test_one_stop_is_not_a_route(self) -> None:
        assert plan_rows(TRIPS["ready"])["multiStop"] is False


def test_a_button_is_added_only_where_a_form_has_none() -> None:
    """Per surface: a panel with its own button must not stop an inline form getting one."""
    inline = _surface(
        "inline-1",
        [
            {"id": "who", "component": "TravelerCounter", "label": "Travellers", "value": {"@path": "/trip/travelers"}},
            {"id": "root", "component": "Column", "children": ["who"]},
        ],
    )
    panel = _surface(
        "sidebar",
        [
            {"id": "note", "component": "TextField", "label": "Note", "value": {"@path": "/panel/note"}},
            {"id": "go-face", "component": "Text", "text": "Go"},
            {"id": "go", "component": "Button", "child": "go-face", "action": {"event": {"name": "go", "context": {}}}},
            {"id": "root", "component": "Column", "children": ["note", "go"]},
        ],
    )
    both = ensure_commit_button(copy.deepcopy(inline) + copy.deepcopy(panel))
    ids = {
        message["updateComponents"]["surfaceId"]: {n["id"] for n in message["updateComponents"]["components"]}
        for message in both
        if "updateComponents" in message
    }
    assert "__commit" in ids["inline-1"]
    assert "__commit" not in ids["sidebar"]
