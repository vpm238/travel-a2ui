"""One surface, components from two catalogs, each naming its own.

`parser_for(surface_id, *also)` has taken extra catalogs since 1.0 and its
docstring says a surface may mix them. Nothing in the app passes a second one
and nothing asserted it worked, which is the state a capability is in just
before somebody discovers it does not: the travel catalog is the only one this
deployment serves, so the first person to add another would be the first to
find out.

What 1.0 actually says is that `catalogId` lives on the component, and the
surface's own is a default. So the test is not "does it compile" — it is
whether each component comes out naming the catalog it came from, because that
is what lets a renderer resolve two vocabularies on one surface.
"""

from __future__ import annotations

from typing import Any

import pytest
from a2ui.core.catalog.catalog import Catalog

from travel_a2ui.brain.catalog import PROTOCOL_VERSION, parser_for
from travel_a2ui.brain.express import as_wire

TRAVEL = "https://travel-a2ui.dev/catalogs/a2ui-travel/catalog.json"
EXTRA = "https://example.test/catalogs/extra/catalog.json"


@pytest.fixture(scope="module")
def extra() -> Catalog:
    """A second catalog holding one component the travel catalog has not.

    Deliberately not a travel component: a name that exists in both would pass
    this test by resolving to the wrong catalog.
    """
    return Catalog.from_json(
        {
            "$schema": "https://a2ui.org/specification/v1_0/json/catalog.json",
            "$id": EXTRA,
            "catalogId": EXTRA,
            "protocolVersion": PROTOCOL_VERSION,
            "title": "Extra",
            "description": "One component the travel catalog does not have.",
            "components": {
                "Stamp": {
                    "type": "object",
                    "properties": {
                        "component": {"const": "Stamp"},
                        "id": {"type": "string"},
                        "label": {"type": "string", "description": "What it says."},
                    },
                    "required": ["component", "id"],
                    "additionalProperties": False,
                }
            },
            "functions": {},
        }
    )


def components(extra: Catalog, source: str) -> list[dict[str, Any]]:
    wire = as_wire(parser_for("inline-1", extra).compile(source, is_final=True))
    return wire[0]["createSurface"]["components"]


class TestBothVocabulariesResolve:
    def test_a_name_from_the_second_catalog_compiles(self, extra: Catalog) -> None:
        drawn = components(extra, 'mark = Stamp(label="paid")\nroot = Column([mark])')
        assert [node["component"] for node in drawn] == ["Stamp", "Column"]

    def test_and_a_travel_name_still_does_beside_it(self, extra: Catalog) -> None:
        drawn = components(
            extra,
            'mark = Stamp(label="paid")\n'
            'head = Text("Receipt", variant="h3")\n'
            "root = Column([head, mark])",
        )
        assert {node["component"] for node in drawn} == {"Stamp", "Text", "Column"}

    def test_a_name_in_neither_is_still_refused(self, extra: Catalog) -> None:
        """Mixing widens the vocabulary; it does not stop checking it."""
        with pytest.raises(Exception):
            components(extra, 'mark = Sticker(label="paid")\nroot = Column([mark])')


class TestEachComponentNamesItsOwnCatalog:
    """The part that makes mixing mean anything to a renderer."""

    def test_the_borrowed_one_carries_the_second_catalog(self, extra: Catalog) -> None:
        drawn = components(extra, 'mark = Stamp(label="paid")\nroot = Column([mark])')
        stamp = next(node for node in drawn if node["component"] == "Stamp")
        assert stamp["catalogId"] == EXTRA

    def test_and_the_travel_ones_carry_the_travel_catalog(self, extra: Catalog) -> None:
        drawn = components(
            extra, 'mark = Stamp(label="paid")\nhead = Text("Receipt")\nroot = Column([head, mark])'
        )
        for node in drawn:
            if node["component"] == "Stamp":
                continue
            assert node["catalogId"] == TRAVEL, node

    def test_one_catalog_alone_says_it_once_on_the_surface(self) -> None:
        """The default, which is what every surface this app draws uses.

        Worth pinning beside the mixed case: naming the catalog per component
        when there is only one would put the same URL on all thirty of them.
        """
        wire = as_wire(parser_for("inline-1").compile('head = Text("Hi")\nroot = Column([head])'))
        surface = wire[0]["createSurface"]
        assert surface["catalogId"] == TRAVEL
        assert all("catalogId" not in node for node in surface["components"])
