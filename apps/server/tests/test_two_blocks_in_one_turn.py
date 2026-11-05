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

from travel_a2ui.brain.finishing import finish, stack_blocks
from travel_a2ui.brain.catalog import PROTOCOL_VERSION

SURFACE = "inline-1"


def block(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "version": PROTOCOL_VERSION,
            "updateComponents": {"surfaceId": SURFACE, "components": components},
        }
    ]


ROUTE = block(
    [
        {
            "id": "when",
            "component": "DateRangePicker",
            "label": "Dates",
            "start": {"@path": "/trip/startDate"},
            "end": {"@path": "/trip/endDate"},
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
            "value": {"@path": "/trip/travelers"},
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
        # is `ensure_commit_button` doing its usual job and not composition.
        assert held["root"]["children"][0] == "when"


class TestBothBlocksSurvive:
    def test_neither_block_replaces_the_other(self) -> None:
        held = drawn(ROUTE, PARTY)
        live = reachable(held)
        assert "when" in live, "the first block's date picker was lost"
        assert any(held[i].get("component") == "TravelerCounter" for i in live)

    def test_root_holds_both_in_the_order_they_were_written(self) -> None:
        held = drawn(ROUTE, PARTY)
        assert held["root"]["children"] == ["b0_root", "b1_root"]

    def test_the_second_block_is_renamed_so_nothing_collides(self) -> None:
        held = drawn(ROUTE, PARTY)
        assert "b1_who" in held and "b1_go" in held
        assert held["b1_go"]["child"] == "b1_label", "references follow the rename"


class TestOnePressSendsBoth:
    def test_both_blocks_answer_on_one_surface(self) -> None:
        """The whole point: one final submit, not one per block.

        The values travel as the surface's data model (`sendDataModel`), so
        what makes one press carry both blocks is that both are one surface.
        """
        held = drawn(ROUTE, PARTY)
        bound = {
            value["@path"]
            for node_id in reachable(held)
            for value in held[node_id].values()
            if isinstance(value, dict) and "@path" in value
        }
        assert "/trip/travelers" in bound, "its own block"
        assert {"/trip/startDate", "/trip/endDate"} <= bound, "and the block before it"

    def test_there_is_exactly_one_thing_to_press(self) -> None:
        held = drawn(ROUTE, PARTY)
        pressable = [
            node_id
            for node_id in reachable(held)
            if held[node_id].get("component") == "Button" and held[node_id].get("action")
        ]
        assert len(pressable) == 1, f"one final submit, found {pressable}"


# The duplicate-heading pass is gone, and its tests with it.
#
# `drop_repeated_headings` deleted a heading when a sibling macro already drew
# one. The duplicate was real — a turn that wrote "Outbound flights" above a
# `Flights()` that draws its own heading — but the host does not get to edit
# the agent's composition. A pass that removes components the agent wrote is
# the host deciding the layout, whatever the components were, so this went
# back to being a prompt problem. See `brain/finishing/__init__.py`.


class TestTheFormsButtonSaysWhatItDoes:
    """`Ask()`'s submit button, which was labelled "Flying from".

    The airports loop bound its own `label` and so shadowed the button's label,
    which is a parameter of the macro. The loop left it holding "Flying from" —
    its last entry — and the button at the bottom of the form rendered that.
    Only when a picker was drawn at all, which is most opening turns.
    """

    @staticmethod
    def _button_text(label: str | None = None) -> str:
        from travel_a2ui.brain.catalog import parser_for
        from travel_a2ui.brain.express import as_wire
        from travel_a2ui.brain.finishing import finish
        from travel_a2ui.brain.macros import expand

        trip = {"destination": "Madrid", "travelers": 2}
        airports = {"from": [{"value": "JFK", "label": "New York (JFK)"}], "to": []}
        said = '"Anything else?"' + (f', "{label}"' if label else "")
        src = f'surface("inline-1")\nform = Ask({said})\nroot = Column([form])'
        drawn = finish(
            as_wire(expand(parser_for("inline-1").compile(src, is_final=True), trip, airports)),
            trip,
        )
        components = {c["id"]: c for c in drawn[0]["createSurface"]["components"]}
        button = next(c for c in components.values() if c["component"] == "Button")
        return components[button["child"]]["text"]

    def test_it_says_find_flights_by_default(self) -> None:
        assert self._button_text() == "Find flights", (
            "the button is wearing a picker's label"
        )

    def test_and_what_the_agent_asked_for_when_it_asked(self) -> None:
        assert self._button_text("Price it") == "Price it"


class TestWhatGoesOutIsStillA2ui:
    def test_a_renderer_holding_this_catalog_accepts_both_blocks(self) -> None:
        """Fed through the SDK's own renderer mirror, in the order they go out.

        The second block's ids were prefixed `b1-`, and A2UI 1.0 ids are UAX #31
        identifiers: a hyphen is not one. Every surface that took a second block
        — a pre-draw then the agent's card, a route then a party — went out with
        ids the SDK rejects, and nothing here asked.
        """
        from a2ui.utils.renderer_state import RendererState

        from travel_a2ui.brain.catalog import CATALOG

        renderer = RendererState([CATALOG])
        renderer.apply(
            [
                {
                    "version": PROTOCOL_VERSION,
                    "createSurface": {"surfaceId": SURFACE, "catalogId": CATALOG.catalog_id},
                }
            ]
        )
        state: dict[str, Any] = {}
        carried: dict[str, dict[str, None]] = {}
        for index, messages in enumerate((ROUTE, PARTY)):
            out = finish(
                stack_blocks(copy.deepcopy(messages), SURFACE, index, state), {}, carried=carried
            )
            renderer.apply(out)
