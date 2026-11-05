"""The catalog the model is shown, as the A2UI SDK prunes it.

`scripts/build_skills.py` narrows the travel catalog with the SDK's
`ComponentPruningTransformer` and `FunctionPruningTransformer` before the
`SkillGenerator` writes a prompt from it. These pin what that leaves: exactly
the allow-list in `agent-components.json`, with the unions narrowed to match,
the definitions that make a catalog a catalog intact, and the macros added on
top — so a change to the allow-list, or to the SDK's pruning, shows up here
rather than as a prompt that quietly documents something else.

Run in its own CI job against the newest SDK, so an upstream change to pruning
is caught the day it ships.
"""

from __future__ import annotations

import json
import pathlib
import sys
import warnings

import pytest

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "apps" / "server" / "src"))

pytest.importorskip(
    "a2ui.catalog_transformers",
    reason="the reference A2UI SDK is not installed (pip install a2ui-agent-sdk)",
)

import build_skills  # noqa: E402

ALLOW = json.loads(build_skills.PRUNING.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def source() -> dict:
    return json.loads(build_skills.CATALOG.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def shown(source, tmp_path_factory):
    return build_skills.pruned_catalog(source, tmp_path_factory.mktemp("catalog"))


def _union(document: dict, name: str) -> set[str]:
    return {
        entry["$ref"].rsplit("/", 1)[-1]
        for entry in document["$defs"][name]["oneOf"]
        if isinstance(entry, dict) and "$ref" in entry
    }


def test_only_the_allowed_components_and_the_macros(shown):
    macros = {"Ask", "Flights", "Highlights", "Itinerary", "Stays", "Trip"}
    assert set(shown.components) == set(ALLOW["allowedComponents"]) | macros


def test_only_the_allowed_functions(shown, source):
    assert set(shown.functions) == set(ALLOW["allowedFunctions"]) & set(source["functions"])


def test_the_unions_list_what_is_kept(shown):
    document = shown.to_json()
    assert _union(document, "anyComponent") == set(shown.components)
    assert _union(document, "anyFunction") == set(shown.functions)


def test_an_excluded_component_is_never_shown(shown):
    for name in ALLOW["excluded"]:
        assert name not in shown.components, f"{name} is excluded but offered"


def test_the_source_catalog_is_untouched(shown, source):
    assert "Video" in source["components"]
    assert "regex" in source["functions"]


def test_the_catalog_definitions_survive(shown):
    """`anyComponent` and `anyFunction` are pointed at from outside the catalog.

    A pruning pass that treated "unreferenced inside" as "unused" would delete
    exactly the definitions that make a catalog a catalog.
    """
    assert {"anyComponent", "anyFunction"} <= set(shown.to_json()["$defs"])
