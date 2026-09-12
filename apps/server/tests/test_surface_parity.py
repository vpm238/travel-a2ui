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

from travel_a2ui.surface import (
    STANDING_SURFACES,
    bind_commit_context,
    bind_derived_labels,
    plan_rows,
    seed_surface_trip,
    strip_panel_actions,
    trip_updates,
)

ROOT = pathlib.Path(__file__).resolve().parents[3]
GOLDEN = json.loads(
    (ROOT / "tools" / "parity" / "__golden__" / "surface.json").read_text("utf-8")
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
        {"version": "v0.9.1", "createSurface": created},
        {"version": "v0.9.1", "updateComponents": {"surfaceId": surface_id, "components": components}},
    ]


#: The same surfaces the capture script built, each chosen for one pass.
SURFACES = {
    "editors with a button that binds nothing": lambda: _surface(
        "inline-1",
        [
            {"id": "from", "component": "TextField", "label": "From", "text": {"path": "/trip/origin"}},
            {
                "id": "when",
                "component": "DateRangePicker",
                "label": "Dates",
                "start": {"path": "/trip/startDate"},
                "end": {"path": "/trip/endDate"},
            },
            {"id": "who", "component": "TravelerCounter", "label": "Travelers", "value": {"path": "/trip/travelers"}},
            {"id": "go", "component": "Button", "label": "Search", "action": {"event": {"name": "search_flights", "context": {}}}},
            {"id": "root", "component": "Column", "children": ["from", "when", "who", "go"]},
        ],
    ),
    "a button that already bound one thing itself": lambda: _surface(
        "inline-1",
        [
            {"id": "from", "component": "TextField", "label": "From", "text": {"path": "/trip/origin"}},
            {"id": "who", "component": "TravelerCounter", "label": "Travelers", "value": {"path": "/trip/travelers"}},
            {
                "id": "go",
                "component": "Button",
                "label": "Search",
                "action": {"event": {"name": "search_flights", "context": {"departingFrom": {"path": "/trip/origin"}}}},
            },
            {"id": "root", "component": "Column", "children": ["from", "who", "go"]},
        ],
    ),
    "editors and no button at all, which is a dead end": lambda: _surface(
        "inline-1",
        [
            {"id": "from", "component": "TextField", "label": "From", "text": {"path": "/trip/origin"}},
            {"id": "who", "component": "TravelerCounter", "label": "Travelers", "value": {"path": "/trip/travelers"}},
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
                "start": {"path": "/trip/startDate"},
                "end": {"path": "/trip/endDate"},
            },
            {"id": "a", "component": "Button", "label": "Search flights", "action": {"event": {"name": "search_flights", "context": {}}}},
            {"id": "b", "component": "Button", "label": "Search hotels", "action": {"event": {"name": "search_hotels", "context": {}}}},
            {"id": "root", "component": "Column", "children": ["when", "a", "b"]},
        ],
    ),
    "colliding key names from two different paths": lambda: _surface(
        "inline-1",
        [
            {"id": "a", "component": "TextField", "label": "From", "text": {"path": "/trip/origin"}},
            {"id": "b", "component": "TextField", "label": "Leg from", "text": {"path": "/leg/origin"}},
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
                "start": {"path": "/trip/startDate"},
                "end": {"path": "/trip/endDate"},
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
                "start": {"path": "/trip/startDate"},
                "end": {"path": "/trip/endDate"},
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
                "start": {"path": "/trip/startDate"},
                "end": {"path": "/trip/endDate"},
            },
            {"id": "root", "component": "Column", "children": ["when"]},
        ],
        {"trip": {"startDate": "2027-06-01"}},
    ),
    "a template row, whose path is a collection and not an answer": lambda: _surface(
        "inline-1",
        [
            {"id": "row", "component": "Text", "text": {"path": "name"}},
            {"id": "list", "component": "List", "children": {"path": "/hotels", "componentId": "row"}},
            {"id": "pick", "component": "TextField", "label": "Note", "text": {"path": "/trip/neighborhood"}},
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
    messages = SURFACES[name]()
    actual = strip_panel_actions(
        bind_derived_labels(bind_commit_context(seed_surface_trip(messages, TRIPS["ready"]))),
        STANDING_SURFACES,
    )
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
        # And it carries the answer, or it is a button that sends nothing.
        context = commit["action"]["event"]["context"]
        assert {binding["path"] for binding in context.values()} == {
            "/trip/origin",
            "/trip/travelers",
        }
        root = next(node for node in components if node["id"] == "root")
        assert "__commit" in root["children"]

    def test_a_key_the_model_chose_is_not_renamed(self) -> None:
        result = GOLDEN["surfaces"]["a button that already bound one thing itself"]
        components = result[1]["updateComponents"]["components"]
        context = next(n for n in components if n["id"] == "go")["action"]["event"]["context"]
        # `departingFrom` survives: the model names things better than an
        # algorithm splitting on slashes, and a context that changes shape
        # between turns is worse than an ugly key.
        assert context["departingFrom"] == {"path": "/trip/origin"}
        assert not any(
            key != "departingFrom" and value == {"path": "/trip/origin"}
            for key, value in context.items()
        ), "the same path must not be bound twice under two names"

    def test_a_template_path_is_not_mistaken_for_an_answer(self) -> None:
        """`/hotels` is a collection to repeat over, not a value someone edited."""
        result = GOLDEN["surfaces"]["a template row, whose path is a collection and not an answer"]
        components = result[1]["updateComponents"]["components"]
        context = next(n for n in components if n["id"] == "go")["action"]["event"]["context"]
        paths = {binding["path"] for binding in context.values()}
        assert "/hotels" not in paths
        assert "/trip/neighborhood" in paths

    def test_a_literal_night_count_becomes_a_live_one(self) -> None:
        result = GOLDEN["surfaces"]["a night count written as literal text"]
        node = next(
            n
            for n in result[1]["updateComponents"]["components"]
            if n["id"] == "when"
        )
        assert node["nightsLabel"]["call"] == "formatString"
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

    def test_the_plan_is_seeded_even_when_nothing_is_decided(self) -> None:
        """A panel drawn before anything is decided must not render blank."""
        messages = seed_surface_trip(_surface("sidebar", []), {})
        data_model = messages[0]["createSurface"]["dataModel"]
        assert data_model["trip"] == {}
        assert data_model["plan"]["total"] > 0
        assert data_model["plan"]["steps"], "the sequence it is about to walk through"


class TestPlanRowsReadCorrectly:
    def test_a_skipped_stage_says_so(self) -> None:
        rows = plan_rows(TRIPS["skipping"])
        stay = next(step for step in rows["steps"] if step["stage"] == "stay")
        assert stay["mark"] == "–"
        assert stay["line"] == "– Somewhere to stay — not needed"

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


def test_the_passes_do_not_share_state_between_surfaces() -> None:
    """Each pass mutates the messages it is given; two surfaces must not mix.

    The commit binder collects editable paths per surface into one dict. Keying
    that wrong — or letting a default leak across — would give an inline card's
    button the panel's paths, which is a payload nobody asked for and nothing
    would report.
    """
    inline = SURFACES["editors with a button that binds nothing"]()
    panel = _surface(
        "sidebar",
        [
            {"id": "note", "component": "TextField", "label": "Note", "text": {"path": "/panel/note"}},
            {"id": "go", "component": "Button", "label": "Go", "action": {"event": {"name": "go", "context": {}}}},
            {"id": "root", "component": "Column", "children": ["note", "go"]},
        ],
    )
    both = bind_commit_context(copy.deepcopy(inline) + copy.deepcopy(panel))

    inline_button = next(
        node
        for message in both
        if message.get("updateComponents", {}).get("surfaceId") == "inline-1"
        for node in message["updateComponents"]["components"]
        if node["id"] == "go"
    )
    paths = {b["path"] for b in inline_button["action"]["event"]["context"].values()}
    assert "/panel/note" not in paths
