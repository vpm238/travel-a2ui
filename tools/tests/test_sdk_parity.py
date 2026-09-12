"""Our pruning against `A2uiCatalog.with_pruning` from the official SDK.

Pruning decides what the model is allowed to draw. Ours and the reference
disagreeing would mean the prompt documents one vocabulary while the upstream
tooling assumes another — so the two are diffed on the same catalog, and this is
what keeps the component half a rename the day upstream is enough on its own.

Skips when the SDK is not installed, so the light CI job stays light.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from prune import with_pruning  # noqa: E402

CATALOG = ROOT / "catalogs" / "a2ui-travel" / "catalog.json"

pytest.importorskip(
    "a2ui.schema.catalog",
    reason="the reference A2UI SDK is not installed (pip install a2ui-agent-sdk)",
)

ALLOWED = ["Text", "Row", "Column", "Button", "FlightOption", "HotelCard"]


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def reference(schema: dict, allowed: list[str]) -> dict:
    from a2ui.schema.catalog import A2uiCatalog

    catalog = A2uiCatalog(
        version="v0.9.1",
        name="travel",
        s2c_schema={},
        common_types_schema={},
        catalog_schema=schema,
    )
    return catalog.with_pruning(allowed_components=allowed).catalog_schema


def test_same_components_survive(schema):
    assert sorted(with_pruning(schema, allowed_components=ALLOWED)["components"]) == sorted(
        reference(schema, ALLOWED)["components"]
    )


def test_same_union_survives(schema):
    def union(document: dict) -> list[str]:
        return sorted(
            entry["$ref"]
            for entry in document["$defs"]["anyComponent"]["oneOf"]
            if isinstance(entry, dict) and "$ref" in entry
        )

    assert union(with_pruning(schema, allowed_components=ALLOWED)) == union(
        reference(schema, ALLOWED)
    )


def test_neither_drops_a_structural_definition(schema):
    assert sorted(with_pruning(schema, allowed_components=ALLOWED)["$defs"]) == sorted(
        reference(schema, ALLOWED)["$defs"]
    )
