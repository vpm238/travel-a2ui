"""The validators, checked against the wire they claim to read.

These are the probes that decide whether a change shipped or not —
`tools/validate/journey.py` drives the turn loop in process, `voice.py` drives a
real websocket, `press.mjs` drives Chromium. Nothing tested them, and over this
feature's life they produced more false findings than the product produced bugs:
a journey reporting "0 party counters" against a surface that had three, a
"NOTHING TO PRESS" against a card a browser could see and press, and most
recently "0 hop(s) ticketed" on scripts `press.mjs` walks cleanly.

That last one is the case these tests exist for. A2UI 1.0 renamed the binding
key from `path` to `@path`. `journey.py` resolves a press's context by looking
for that key, the matcher beside it was updated and this one was not, so every
press handed the agent `{"id.@path": "id"}` — the binding names rather than the
fare they point at. The agent then sometimes inferred the fare from the data
model and sometimes called `release_decision` instead, which read from the
outside as a flaky product.

An instrument that silently reads its own rename as a product bug costs more
than no instrument, because it is believed. So: the wire format each validator
parses is asserted against the catalog's own version of it.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

from travel_a2ui.brain.catalog import PROTOCOL_VERSION

_VALIDATE = pathlib.Path(__file__).resolve().parents[3] / "tools" / "validate"


@pytest.fixture(scope="module")
def journey():
    sys.path.insert(0, str(_VALIDATE))
    try:
        import journey as module

        return module
    finally:
        sys.path.remove(str(_VALIDATE))


#: What the compiler actually emits for a binding, as the renderer reads it.
#:
#: Asserted rather than assumed, so a future rename fails here — in a test that
#: says what to change — instead of in a validator that keeps running and
#: reporting the product broken.
BINDING_KEY = "@path"


def test_the_wire_still_spells_a_binding_the_way_the_validators_expect() -> None:
    from travel_a2ui.brain.catalog import parser_for
    from travel_a2ui.brain.express import as_wire

    assert PROTOCOL_VERSION == "1.0", (
        f"the protocol moved to {PROTOCOL_VERSION!r}; check every validator's "
        "binding key before trusting another run"
    )
    drawn = as_wire(
        parser_for("inline-1").compile(
            'surface("inline-1")\n'
            'card = Text($/trip/destination)\n'
            "root = Column([card])",
            is_final=True,
        )
    )
    assert BINDING_KEY in str(drawn), (
        f"the compiler no longer writes {BINDING_KEY!r}, so every validator that "
        f"looks for it is about to report the product broken: {str(drawn)[:300]}"
    )


class TestJourneyResolvesAPressTheWayABrowserWould:
    """A press carries the row's values, never the names of its bindings."""

    ROWS = [
        {"id": "EW8405", "price": "€74", "airline": "Eurowings", "departTime": "10:45"},
        {"id": "SK573", "price": "€75", "airline": "SAS", "departTime": "10:09"},
    ]

    def _fare(self, binding: str) -> list[dict]:
        """A fare card as the `Flights()` macro writes it, in one spelling."""
        return [
            {
                "id": "fare0",
                "component": "FlightOption",
                "componentProperties": {
                    "airline": {binding: "airline"},
                    "action": {
                        "event": {
                            "name": "select_flight",
                            "context": {
                                "id": {binding: "id"},
                                "price": {binding: "price"},
                                "airline": {binding: "airline"},
                                "departTime": {binding: "departTime"},
                            },
                        }
                    },
                },
            }
        ]

    @pytest.mark.parametrize("binding", ["@path", "path"])
    def test_in_either_spelling(self, journey, binding: str) -> None:
        """1.0 writes `@path`; 0.9 wrote `path`. Both resolve, so a bump cannot blind it."""
        found = journey.pressable(
            self._fare(binding), "FlightOption", {}, {"/flights": self.ROWS}
        )
        assert found is not None, f"{binding}: nothing pressable on a card with an action"
        name, context = found
        assert name == "select_flight"
        assert context == {
            "id": "EW8405",
            "price": "€74",
            "airline": "Eurowings",
            "departTime": "10:45",
        }, f"{binding}: the press carries {context}"

    def test_and_never_hands_over_a_binding_name(self, journey) -> None:
        """The exact failure: `{"id.@path": "id"}` reaching the agent as a fact."""
        _, context = journey.pressable(
            self._fare("@path"), "FlightOption", {}, {"/flights": self.ROWS}
        )
        for key, value in context.items():
            assert "@path" not in key, f"an unresolved binding reached the agent: {key}"
            assert value not in ("id", "price", "airline", "departTime"), (
                f"{key} came through as the binding's name rather than its value: {value!r}"
            )

    def test_a_press_on_a_card_with_no_action_is_not_a_press(self, journey) -> None:
        """The panel's rows are records. `Trip()` draws them without an action on purpose."""
        record = [
            {
                "id": "panelFare",
                "component": "FlightOption",
                "componentProperties": {"airline": {"@path": "/trip/airline"}},
            }
        ]
        assert journey.pressable(record, "FlightOption", {}, {}) is None
