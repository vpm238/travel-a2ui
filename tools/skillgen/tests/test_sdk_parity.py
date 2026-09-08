"""Parity between our signature generator and Google's reference one.

`skillgen` re-implements `CatalogSchemaHelper` and `ExpressPromptGenerator` from
google/a2ui so that generating a skill does not require the ADK dependency tree.
That is a reasonable trade only while the two agree — a signature block that has
quietly drifted teaches the model a component API that no longer exists.

So: when the reference SDK is importable, diff the two character for character.
When it is not, skip. CI runs both ways — light by default, and with the SDK
installed in the parity job.

    pip install a2ui-agent-sdk && pytest tools/skillgen/tests/test_sdk_parity.py
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "skillgen" / "src"))

from skillgen import CatalogHelper, ExpressFormat  # noqa: E402

CATALOG = ROOT / "catalogs" / "a2ui-travel" / "catalog.json"

reference = pytest.importorskip(
    "a2ui.inference_formats.experimental.express.prompt_generator",
    reason="the reference A2UI SDK is not installed (pip install a2ui-agent-sdk)",
)


@pytest.fixture(scope="module")
def reference_generator():
    from a2ui.core.catalog import Catalog
    from a2ui.inference_formats.experimental.express.format import ExpressFormat as SdkFormat

    schema = json.loads(CATALOG.read_text(encoding="utf-8"))
    catalog = Catalog.from_json(
        catalog_schema=schema, spec_version="v0.9.1", catalog_id=schema["catalogId"]
    )
    return SdkFormat(catalog=catalog).prompt_generator


@pytest.fixture(scope="module")
def helper() -> CatalogHelper:
    return CatalogHelper.from_path(CATALOG)


def test_component_signatures_match(reference_generator, helper):
    assert ExpressFormat().generate_component_signatures(
        helper
    ) == reference_generator.generate_component_signatures()


def test_function_signatures_match(reference_generator, helper):
    assert ExpressFormat().generate_function_signatures(
        helper
    ) == reference_generator.generate_function_signatures()


def test_catalog_block_matches(reference_generator, helper):
    assert ExpressFormat().generate_catalog_instructions(
        helper
    ) == reference_generator.catalog_description(include_schema=True)


def test_property_order_matches(reference_generator, helper):
    reference_helper = reference_generator.helper
    for name in helper.components:
        assert helper.get_component_properties(name) == reference_helper.get_component_properties(
            name
        ), f"{name} property order drifted"


def test_required_sets_match(reference_generator, helper):
    reference_helper = reference_generator.helper
    for name in helper.components:
        assert helper.get_component_required(name) == reference_helper.get_component_required(name)


class TestPruningParity:
    """Our `with_pruning` against `A2uiCatalog.with_pruning` from the SDK.

    Pruning decides what the model is allowed to draw. Ours and the reference
    disagreeing would mean the prompt documents one vocabulary while the
    upstream tooling assumes another — so the two are diffed on the same
    catalog, and this is the test that makes adopting the upstream call a
    rename rather than a leap.
    """

    ALLOWED = ["Text", "Row", "Column", "Button", "FlightOption", "HotelCard"]

    @staticmethod
    def _reference(schema, allowed):
        from a2ui.schema.catalog import A2uiCatalog

        catalog = A2uiCatalog(
            version="v0.9.1",
            name="a2ui-travel",
            s2c_schema={},
            common_types_schema={},
            catalog_schema=schema,
        )
        return catalog.with_pruning(allowed_components=allowed).catalog_schema

    def test_same_components_survive(self):
        from skillgen.catalog import with_pruning

        schema = json.loads(CATALOG.read_text(encoding="utf-8"))
        assert sorted(with_pruning(schema, allowed_components=self.ALLOWED)["components"]) == sorted(
            self._reference(schema, self.ALLOWED)["components"]
        )

    def test_same_union_survives(self):
        from skillgen.catalog import with_pruning

        schema = json.loads(CATALOG.read_text(encoding="utf-8"))

        def union(document):
            return sorted(
                entry["$ref"]
                for entry in document["$defs"]["anyComponent"]["oneOf"]
                if isinstance(entry, dict) and "$ref" in entry
            )

        assert union(with_pruning(schema, allowed_components=self.ALLOWED)) == union(
            self._reference(schema, self.ALLOWED)
        )

    def test_neither_drops_a_structural_definition(self):
        """`anyComponent` is pointed at from outside the catalog, never inside."""
        from skillgen.catalog import with_pruning

        schema = json.loads(CATALOG.read_text(encoding="utf-8"))
        assert sorted(with_pruning(schema, allowed_components=self.ALLOWED)["$defs"]) == sorted(
            self._reference(schema, self.ALLOWED)["$defs"]
        )
