"""Our pruning against `A2uiCatalog.with_pruning` from the official SDK.

Pruning decides what the model is allowed to draw. Ours and the reference
disagreeing would mean the prompt documents one vocabulary while the upstream
tooling assumes another — so the two are diffed on the same catalog, and this is
what keeps the component half a rename the day upstream is enough on its own.

Skips when the SDK is not installed, so the light CI job stays light.

**Against the transformer, since agent-sdk 0.9.** `A2uiCatalog.with_pruning`
is gone: pruning is a catalog *transformer* now, and messages are pruned by
the format rather than the catalog. The question this file asks did not change
with it — do we and upstream agree about which components survive — so it asks
the new owner. It was written against the old one, and when that disappeared
the module skipped itself whole and pytest exited 5 for collecting nothing,
which CI read as a failure and which is the right answer for the wrong reason:
a parity test that cannot find its reference is not passing.
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
    "a2ui.catalog_transformers",
    reason="the reference A2UI SDK is not installed (pip install a2ui-agent-sdk)",
)

ALLOWED = ["Text", "Row", "Column", "Button", "FlightOption", "HotelCard"]


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def reference(schema: dict, allowed: list[str]) -> dict:
    """What upstream's own pruning leaves of this catalog."""
    from a2ui.catalog_transformers import ComponentPruningTransformer
    from a2ui.core.catalog import CatalogApi

    catalog = CatalogApi.from_json(schema)
    return ComponentPruningTransformer(allowed).transform(catalog).catalog_schema


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
    """Of what the catalog *declares*, both keep the same definitions.

    Not an equality any more, and the difference is the reference adding
    rather than us dropping: loading a catalog resolves it against the spec's
    own common types, so upstream's `$defs` gains `DataBinding`,
    `AccessibilityAttributes` and — new at 1.0 — `FunctionCommon` and
    `IndexSystemFunction`, none of which were ever in this file. Comparing the
    two sets whole asked whether upstream had bundled the spec, which is not a
    question about pruning.

    What pruning is answerable for is everything the catalog brought with it.
    """
    declared = set(schema["$defs"])
    ours = set(with_pruning(schema, allowed_components=ALLOWED)["$defs"])
    theirs = set(reference(schema, ALLOWED)["$defs"])
    assert theirs & declared <= ours, "upstream kept a definition we dropped"
