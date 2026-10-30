"""The host's whole share of a lookup: the rows, at an address the brief names.

This replaces `test_skeleton_parity.py`, and the thing it no longer tests is
the point. That file held a golden over two Express blueprints the host
compiled at import time — a flight list and a hotel list, layout and fields and
events and four blank rows — because the host drew the cards and the tool
result told the model not to. The interface was in Python.

What is left to test is narrow on purpose: that the rows go where the brief
says they go, that nothing else goes with them, and that a lookup which found
nothing says so by filing nothing rather than by filing an empty array over a
card somebody is reading.
"""

from __future__ import annotations

from typing import Any

import pytest

from travel_a2ui.brain.catalog import PROTOCOL_VERSION
from travel_a2ui.brain.macros import LANDINGS, file_rows, landing_for, rows_in

FOUND: dict[str, Any] = {
    "flights": [
        {"id": "DY1234", "airline": "Norwegian", "price": "€281"},
        {"id": "SK119", "airline": "SAS", "price": "€138"},
    ],
    "note": "Sample data",
}


class TestTheAddress:
    def test_the_two_lookups_with_a_predictable_shape_have_one(self) -> None:
        assert landing_for("search_flights") == "/flights"
        assert landing_for("search_hotels") == "/hotels"

    @pytest.mark.parametrize(
        "tool", ["estimate_cost", "get_destination", "get_weather", "save_trip", "get_trip"]
    )
    def test_everything_else_has_none(self, tool: str) -> None:
        """A shape nobody can predict is a promise the brief cannot make."""
        assert landing_for(tool) is None
        assert file_rows(tool, FOUND, "inline-1", "v1.0") == []

    def test_the_brief_and_the_host_name_the_same_addresses(self) -> None:
        """The one coupling left between the two sides, so it is asserted.

        The host files rows at `/flights`; the brief tells the agent to write
        `_template($/flights, row)`. If those drift, the agent draws a list
        over an empty path and the cards never appear — and nothing else in
        this suite would notice, because both halves are independently correct.
        """
        import json
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[3]
        catalog = json.loads(
            (root / "catalogs" / "a2ui-travel" / "catalog.json").read_text("utf-8")
        )
        instructions = catalog["instructions"]
        for path, _key in LANDINGS.values():
            assert path in instructions, f"the brief never mentions {path}"


class TestWhatGoesOut:
    def test_one_message_and_it_carries_no_components(self) -> None:
        messages = file_rows("search_flights", FOUND, "inline-7", PROTOCOL_VERSION)
        assert len(messages) == 1
        body = messages[0]
        assert set(body) == {"version", "updateDataModel"}
        assert "createSurface" not in body and "updateComponents" not in body

    def test_the_rows_go_to_the_surface_this_turn_is_answering(self) -> None:
        update = file_rows("search_flights", FOUND, "inline-7", PROTOCOL_VERSION)[0]["updateDataModel"]
        assert update["surfaceId"] == "inline-7"
        assert update["path"] == "/flights"
        assert update["value"] == FOUND["flights"]

    def test_the_whole_array_is_replaced_rather_than_patched(self) -> None:
        """A provider returning three must not leave a fourth behind.

        The agent seeds blank rows to show the shape while the lookup runs, and
        a patch row-by-row would leave the ones it did not reach sitting there
        pending for ever.
        """
        update = file_rows("search_flights", FOUND, "inline-7", PROTOCOL_VERSION)[0]["updateDataModel"]
        assert update["path"] == "/flights", "the array, not an index inside it"
        assert isinstance(update["value"], list)

    def test_it_speaks_the_version_it_is_handed(self) -> None:
        assert (
            file_rows("search_flights", FOUND, "inline-7", PROTOCOL_VERSION)[0]["version"]
            == PROTOCOL_VERSION
        )
        assert file_rows("search_flights", FOUND, "inline-7", "v0.9.1")[0]["version"] == "v0.9.1"

    def test_the_path_keeps_its_unprefixed_spelling(self) -> None:
        """`updateDataModel`'s own `path` is not a binding.

        1.0 reserves `@` for a binding inside a component, and left this key
        alone. Writing `@path` here would be a message no renderer applies.
        """
        update = file_rows("search_flights", FOUND, "inline-7", PROTOCOL_VERSION)[0]["updateDataModel"]
        assert "path" in update and "@path" not in update


class TestALookupThatFoundNothing:
    """A refusal is an answer, and an empty array is not the way to give it."""

    @pytest.mark.parametrize(
        "nothing",
        [None, {}, {"flights": []}, {"flights": "nope"}, "not a dict", 7],
        ids=["none", "empty dict", "empty list", "wrong type", "not a dict", "a number"],
    )
    def test_nothing_is_file_rows(self, nothing: Any) -> None:
        assert rows_in("search_flights", nothing) is None
        assert file_rows("search_flights", nothing, "inline-7", "v1.0") == []

    def test_which_is_not_the_same_as_an_empty_list_of_rows(self) -> None:
        """Filing `[]` would blank a card the traveller is reading.

        "No flights for those dates" is a sentence the agent says; it is not a
        reason to take the last answer off the screen.
        """
        assert file_rows("search_flights", {"flights": []}, "inline-7", "v1.0") == []
