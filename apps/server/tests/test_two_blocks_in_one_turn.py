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
            value["@path"]
            for value in context.values()
            if isinstance(value, dict) and "@path" in value
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


class TestASurfaceDoesNotShowOneHeadingTwice:
    """The heading a turn writes above a macro that already draws it.

    `Flights()` takes a heading and draws it, which is the point of passing
    one. The agent writes one anyway:

        heading = Text("Outbound · JFK → MAD · Mon 12 Apr")
        fares = Flights("Outbound · JFK → MAD · Mon 12 Apr", "/trip/selectedFlight")
        root = Column([heading, fares])

    Both are correct alone and together they put the same line on screen twice.
    Measured over a journey, on every turn that drew fares — and on the return
    too, so one trip collected four of them.
    """

    @staticmethod
    def _children(components: list[dict], of: str) -> list[str]:
        from travel_a2ui.brain.finishing import drop_repeated_headings

        out = drop_repeated_headings([{"createSurface": {"surfaceId": "inline-1", "components": components}}])
        for c in out[0]["createSurface"]["components"]:
            if c["id"] == of:
                return c["children"]
        raise AssertionError(f"{of} is gone")

    HEADING = "Outbound · JFK → MAD · Mon 12 Apr"

    def _recorded(self) -> list[dict]:
        """Exactly the shape a journey recording caught."""
        return [
            {"id": "b1-heading", "component": "Text", "text": self.HEADING, "variant": "h3"},
            {"id": "b1-fares__text_1", "component": "Text", "text": self.HEADING, "variant": "h3"},
            {"id": "b1-fares__list_1", "component": "List", "children": {"path": "/flights"}},
            {"id": "b1-fares", "component": "Column", "children": ["b1-fares__text_1", "b1-fares__list_1"]},
            {"id": "b1-root", "component": "Column", "children": ["b1-heading", "b1-fares"]},
        ]

    def test_the_one_outside_the_macro_goes(self) -> None:
        assert self._children(self._recorded(), "b1-root") == ["b1-fares"]

    def test_and_the_macro_keeps_its_own(self) -> None:
        """The copy next to the list it is a heading for is the one worth keeping."""
        assert self._children(self._recorded(), "b1-fares") == [
            "b1-fares__text_1",
            "b1-fares__list_1",
        ]

    def test_a_heading_nothing_repeats_is_left_alone(self) -> None:
        components = self._recorded()
        components[0] = {**components[0], "text": "Choose your flight out"}
        assert self._children(components, "b1-root") == ["b1-heading", "b1-fares"]

    def test_and_two_different_sections_both_keep_their_headings(self) -> None:
        """A turn drawing the outbound and the return must not lose one of them."""
        components = [
            {"id": "out", "component": "Text", "text": "Outbound", "variant": "h3"},
            {"id": "back", "component": "Text", "text": "Return", "variant": "h3"},
            {"id": "root", "component": "Column", "children": ["out", "back"]},
        ]
        assert self._children(components, "root") == ["out", "back"]

    def test_a_bound_heading_is_never_touched(self) -> None:
        """Two bindings are not known to be equal until they resolve."""
        bound = {"@path": "/trip/destination"}
        components = [
            {"id": "a", "component": "Text", "text": bound},
            {"id": "b__text_1", "component": "Text", "text": bound},
            {"id": "b", "component": "Column", "children": ["b__text_1"]},
            {"id": "root", "component": "Column", "children": ["a", "b"]},
        ]
        assert self._children(components, "root") == ["a", "b"]


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
