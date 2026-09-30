"""A turn may write two blocks. Both stay answerable, and one press sends both.

Writing two is reasonable — one card for the route, one for who is on it — and
it used to lose the first. A renderer replaces components by id and renders
whichever is called `root`, so the second block's root quietly took the first
one's place: the traveller watched the dates and party they were filling in
vanish, leaving only the airports.
"""

from __future__ import annotations

import copy
from typing import Any

from travel_a2ui.brain.surface import finish, stack_blocks

SURFACE = "inline-1"


def block(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "version": "v0.9.1",
            "updateComponents": {"surfaceId": SURFACE, "components": components},
        }
    ]


ROUTE = block(
    [
        {
            "id": "when",
            "component": "DateRangePicker",
            "label": "Dates",
            "start": {"path": "/trip/startDate"},
            "end": {"path": "/trip/endDate"},
        },
        {"id": "root", "component": "Column", "children": ["when"]},
    ]
)

PARTY = block(
    [
        {
            "id": "who",
            "component": "TravelerCounter",
            "label": "Travellers",
            "value": {"path": "/trip/travelers"},
        },
        {"id": "label", "component": "Text", "text": "Search flights"},
        {
            "id": "go",
            "component": "Button",
            "child": "label",
            "action": {"event": {"name": "search", "context": {}}},
        },
        {"id": "root", "component": "Column", "children": ["who", "go"]},
    ]
)


def drawn(*blocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The surface as a renderer would hold it: components replaced by id."""
    # Deep-copied because these passes edit nodes in place, and a fixture
    # shared between tests would otherwise carry one test's commit button into
    # the next — which is exactly the false failure this helper first produced.
    state: dict[str, Any] = {}
    carried: dict[str, dict[str, None]] = {}
    held: dict[str, dict[str, Any]] = {}
    for index, messages in enumerate(blocks):
        out = finish(
            stack_blocks(copy.deepcopy(messages), SURFACE, index, state), {}, carried=carried
        )
        for message in out:
            update = message.get("updateComponents") or message.get("createSurface")
            if not update or update.get("surfaceId") != SURFACE:
                continue
            for node in update.get("components") or []:
                held[node["id"]] = node
    return held


def reachable(held: dict[str, dict[str, Any]]) -> set[str]:
    """Every component the renderer would actually draw, from `root` down."""
    seen: set[str] = set()

    def walk(node_id: str) -> None:
        node = held.get(node_id)
        if node is None or node_id in seen:
            return
        seen.add(node_id)
        for key in ("children", "child"):
            value = node.get(key)
            for child in value if isinstance(value, list) else [value]:
                if isinstance(child, str):
                    walk(child)

    walk("root")
    return seen


class TestOneBlockIsUnchanged:
    def test_it_still_renders_from_root(self) -> None:
        held = drawn(ROUTE)
        assert "when" in reachable(held)
        # A surface of editors with nothing to press gets a commit button, which
        # is `bind_commit_context` doing its usual job and not composition.
        assert held["root"]["children"][0] == "when"


class TestBothBlocksSurvive:
    def test_neither_block_replaces_the_other(self) -> None:
        held = drawn(ROUTE, PARTY)
        live = reachable(held)
        assert "when" in live, "the first block's date picker was lost"
        assert any(held[i].get("component") == "TravelerCounter" for i in live)

    def test_root_holds_both_in_the_order_they_were_written(self) -> None:
        held = drawn(ROUTE, PARTY)
        assert held["root"]["children"] == ["b0-root", "b1-root"]

    def test_the_second_block_is_renamed_so_nothing_collides(self) -> None:
        held = drawn(ROUTE, PARTY)
        assert "b1-who" in held and "b1-go" in held
        assert held["b1-go"]["child"] == "b1-label", "references follow the rename"


class TestOnePressSendsBoth:
    def test_the_button_carries_both_blocks_paths(self) -> None:
        """The whole point: one final submit, not one per block."""
        held = drawn(ROUTE, PARTY)
        button = next(
            held[node_id]
            for node_id in reachable(held)
            if held[node_id].get("component") == "Button" and held[node_id].get("action")
        )
        context = button["action"]["event"]["context"]
        bound = {
            value["path"]
            for value in context.values()
            if isinstance(value, dict) and "path" in value
        }
        assert "/trip/travelers" in bound, "its own block"
        assert "/trip/startDate" in bound, "and the block before it"
        assert "/trip/endDate" in bound

    def test_there_is_exactly_one_thing_to_press(self) -> None:
        held = drawn(ROUTE, PARTY)
        pressable = [
            node_id
            for node_id in reachable(held)
            if held[node_id].get("component") == "Button" and held[node_id].get("action")
        ]
        assert len(pressable) == 1, f"one final submit, found {pressable}"
