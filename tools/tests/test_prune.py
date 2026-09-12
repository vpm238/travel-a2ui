"""Pruning the catalog the model is shown.

Generating the skill is upstream's job now. This is the piece that is not, and
the piece that decides which components and functions ever reach a prompt — so
it keeps its own tests, and `test_sdk_parity.py` diffs it against the real
`A2uiCatalog.with_pruning` whenever the SDK is installed.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from prune import Vocabulary, uses_only, with_pruning  # noqa: E402

CATALOG = ROOT / "catalogs" / "a2ui-travel" / "catalog.json"
SKILLS = ROOT / "skills"
ALLOW = ROOT / "catalogs" / "a2ui-travel" / "agent-components.json"

ALLOWED = ["Text", "Row", "Column", "Button", "FlightOption"]


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


class TestComponents:
    def test_keeps_only_the_named_components(self, schema):
        pruned = with_pruning(schema, allowed_components=ALLOWED)
        assert set(pruned["components"]) == set(ALLOWED)
        assert "Video" in schema["components"], "the source catalog is not mutated"

    def test_drops_the_component_from_the_union_too(self, schema):
        pruned = with_pruning(schema, allowed_components=ALLOWED)
        refs = {
            entry.get("$ref")
            for entry in pruned["$defs"]["anyComponent"]["oneOf"]
            if isinstance(entry, dict)
        }
        assert "#/components/FlightOption" in refs
        assert "#/components/Video" not in refs

    def test_unknown_names_narrow_rather_than_raise(self, schema):
        pruned = with_pruning(schema, allowed_components=["Text", "NoSuchComponent"])
        assert set(pruned["components"]) == {"Text"}

    def test_no_allow_list_is_the_whole_catalog(self, schema):
        assert with_pruning(schema) is schema


class TestFunctions:
    def test_keeps_only_the_named_functions(self, schema):
        pruned = with_pruning(schema, allowed_functions=["formatCurrency", "calcNights"])
        assert set(pruned["functions"]) == {"formatCurrency", "calcNights"}
        # Components are untouched when only functions are named.
        assert set(pruned["components"]) == set(schema["components"])

    def test_drops_the_function_from_its_union(self, schema):
        pruned = with_pruning(schema, allowed_functions=["formatCurrency"])
        refs = {
            entry.get("$ref")
            for entry in pruned["$defs"]["anyFunction"]["oneOf"]
            if isinstance(entry, dict)
        }
        assert "#/functions/regex" not in refs


class TestDefinitions:
    def test_unreachable_defs_are_pruned(self):
        schema = {
            "components": {"Kept": {"$ref": "#/$defs/Used"}},
            "$defs": {
                "Used": {"properties": {"x": {"$ref": "#/$defs/Chained"}}},
                "Chained": {"type": "number"},
                "Orphan": {"type": "boolean"},
            },
        }
        result = with_pruning(schema, allowed_components=["Kept"])
        assert set(result["$defs"]) == {"Used", "Chained"}, "reachable through Used"

    def test_structural_definitions_survive(self, schema):
        """`anyComponent` is pointed at from outside the catalog, never inside.

        A reachability sweep that treats "unreferenced" as "unused" deletes
        exactly the definitions that make a catalog a catalog.
        """
        pruned = with_pruning(schema, allowed_components=ALLOWED)
        assert {"anyComponent", "anyFunction", "theme"} <= set(pruned["$defs"])


class TestExamples:
    """Which worked examples survive, given what the prompt still documents."""

    VOCABULARY = Vocabulary(
        allowed_components={"Column", "Text", "TextField"},
        known_components={"Column", "Text", "Video", "TextField"},
        allowed_functions={"formatCurrency"},
        known_functions={"required", "email", "formatCurrency"},
    )

    def test_an_example_using_a_pruned_component_is_dropped(self):
        assert not uses_only('Column([Video("x")])', self.VOCABULARY)

    def test_an_example_using_a_pruned_check_rule_is_dropped(self):
        # Lower-case and spelled `?rule`, so a component-only scan sails past it.
        assert not uses_only('TextField("Email", $/e, ?required, ?email)', self.VOCABULARY)

    def test_a_surviving_function_is_not_a_reason_to_drop(self):
        assert uses_only('Text(formatCurrency(value: 12, currency: "USD"))', self.VOCABULARY)

    def test_a_name_from_another_catalog_is_not_a_reason_to_drop(self):
        # `Event(` and `_template(` are grammar, not catalog components.
        assert uses_only('Column([Text("hi")], action=Event("go"))', self.VOCABULARY)


class TestShippedSkills:
    def test_the_checked_in_skill_matches_the_allow_list(self):
        """The shipped prompt documents exactly what the catalog allows."""
        allow = json.loads(ALLOW.read_text(encoding="utf-8"))
        body = (SKILLS / "express-monolithic" / "a2ui" / "SKILL.md").read_text(encoding="utf-8")

        # A word boundary, because `Card(` is a substring of `HotelCard(` — a
        # plain `in` test failed on the one component whose name ends in another
        # component's name, which is exactly where this check has to be right.
        def calls(name: str) -> bool:
            return re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}\(", body) is not None

        for name in allow["excluded"]:
            assert not calls(name), f"{name} was pruned but still documented"
        for name in allow["allowedComponents"]:
            assert calls(name), f"{name} is allowed but missing from the prompt"
