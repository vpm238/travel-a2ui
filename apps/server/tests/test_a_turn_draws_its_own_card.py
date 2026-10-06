"""A turn draws its own card, and never over a card already answered.

Express lets a block name the surface it draws into, and the brief's worked
example names one literally — `surface("inline-flights")`. A turn that copied
the example rather than the "Draw into surface `inline-7`" line in its own
prompt therefore drew onto an id it shared with every other turn that copied
it. The renderer merges components by id and draws whichever is called `root`,
so the next such turn replaced the previous card outright: pick a hotel, and
the list of hotels you just picked from disappears as the answer arrives.

Only sometimes — it depends on the model reaching for the example — which is
exactly how it was reported.
"""

from __future__ import annotations

from typing import Any

from travel_a2ui.brain.surface import on_its_own_surface, stack_blocks

TURN = "inline-7"


def components(surface_id: str, *nodes: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": "v0.9.1",
        "updateComponents": {"surfaceId": surface_id, "components": list(nodes)},
    }


def created(surface_id: str) -> dict[str, Any]:
    return {
        "version": "v0.9.1",
        "createSurface": {"surfaceId": surface_id, "catalogId": "catalog.json"},
    }


def surfaces_in(messages: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for message in messages:
        for key in ("createSurface", "updateComponents", "updateDataModel"):
            body = message.get(key)
            if isinstance(body, dict) and isinstance(body.get("surfaceId"), str):
                found.add(body["surfaceId"])
    return found


def test_a_block_that_names_another_surface_lands_on_this_turns_card() -> None:
    block = [
        created("inline-flights"),
        {
            "version": "v0.9.1",
            "updateDataModel": {
                "surfaceId": "inline-flights",
                "path": "/trip/selectedOutbound",
                "contents": "",
            },
        },
        components(
            "inline-flights",
            {"id": "head", "component": "Text", "text": "Outbound"},
            {"id": "root", "component": "Column", "children": ["head"]},
        ),
    ]

    assert surfaces_in(on_its_own_surface(block, TURN)) == {TURN}


def test_the_block_itself_is_untouched_apart_from_the_address() -> None:
    block = [
        components(
            "inline-flights",
            {"id": "head", "component": "Text", "text": "Outbound"},
            {"id": "root", "component": "Column", "children": ["head"]},
        )
    ]

    (readdressed,) = on_its_own_surface(block, TURN)
    assert readdressed["updateComponents"]["components"] == (
        block[0]["updateComponents"]["components"]
    )


def test_a_block_already_on_the_turns_card_is_passed_through_as_is() -> None:
    block = [components(TURN, {"id": "root", "component": "Column", "children": []})]
    assert on_its_own_surface(block, TURN) == block


def test_two_blocks_still_compose_when_one_of_them_named_another_surface() -> None:
    """The readdress happens first, so `stack_blocks` sees one surface.

    Without it the stray block is the one thing `stack_blocks` lets past
    untouched — it composes only what is addressed to this turn — and the
    traveller gets one card of the two halves they were asked for.
    """
    first = [
        components(
            TURN,
            {"id": "when", "component": "Text", "text": "Dates"},
            {"id": "root", "component": "Column", "children": ["when"]},
        )
    ]
    second = [
        components(
            "inline-flights",
            {"id": "who", "component": "Text", "text": "Who"},
            {"id": "root", "component": "Column", "children": ["who"]},
        )
    ]

    state: dict[str, Any] = {}
    out = stack_blocks(on_its_own_surface(first, TURN), TURN, 0, state)
    out += stack_blocks(on_its_own_surface(second, TURN), TURN, 1, state)

    assert surfaces_in(out) == {TURN}
    # Both halves survive, under the one root the press will carry.
    roots = [
        node
        for message in out
        for node in message.get("updateComponents", {}).get("components", [])
        if node.get("id") == "root"
    ]
    assert roots and roots[-1]["children"] == ["b0-root", "b1-root"]
