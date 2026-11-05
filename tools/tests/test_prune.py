"""Which worked examples survive pruning, and what the shipped prompt documents.

Pruning the catalog is the SDK's, and `test_sdk_parity.py` pins what it leaves.
This is the part that is ours: dropping an example that calls something pruned.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from prune import Vocabulary, uses_only  # noqa: E402

CATALOG = ROOT / "catalogs" / "a2ui-travel" / "catalog.json"
SKILLS = ROOT / "skills"
ALLOW = ROOT / "catalogs" / "a2ui-travel" / "agent-components.json"

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
        body = (SKILLS / "express-modular" / "a2ui-travel" / "SKILL.md").read_text(encoding="utf-8")

        # A word boundary, because `Card(` is a substring of `HotelCard(` — a
        # plain `in` test failed on the one component whose name ends in another
        # component's name, which is exactly where this check has to be right.
        def calls(name: str) -> bool:
            return re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}\(", body) is not None

        for name in allow["excluded"]:
            assert not calls(name), f"{name} was pruned but still documented"
        for name in allow["allowedComponents"]:
            assert calls(name), f"{name} is allowed but missing from the prompt"
