"""Tests for the skill generator.

The bar these hold to: a generated skill has to be *usable by a model*, which
means the frontmatter parses, the name says what the skill does rather than how
it works, and every implementation detail that would clutter the description
lives in metadata instead.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "skillgen" / "src"))

from skillgen import (  # noqa: E402
    CatalogHelper,
    DirectJsonFormat,
    ExpressFormat,
    GenerationRequest,
    build_catalog_skill,
    build_core_skill,
    build_monolithic_skill,
    catalog_skill_name,
    generate,
    load_express_examples,
    split_example,
)

CATALOG = ROOT / "catalogs" / "a2ui-travel" / "catalog.json"
EXAMPLES = ROOT / "catalogs" / "a2ui-travel" / "examples"
SKILLS = ROOT / "skills"


@pytest.fixture(scope="module")
def helper() -> CatalogHelper:
    return CatalogHelper.from_path(CATALOG)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """A small YAML reader for exactly the frontmatter shape we emit.

    Deliberately not `pyyaml`: this asserts the file parses under something that
    only knows the documented subset, which is a stronger claim than "a
    permissive parser accepted it".
    """
    assert text.startswith("---\n"), "SKILL.md must open with frontmatter"
    _, block, body = text.split("---\n", 2)

    lines = [line for line in block.splitlines() if line.strip()]
    data: dict = {}
    # (indent of the keys inside it, container)
    stack: list[tuple[int, dict]] = [(0, data)]

    for index, line in enumerate(lines):
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if stripped.startswith("- "):
            continue  # consumed by the key that opened the list

        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()
        container = stack[-1][1]

        key, _, raw = stripped.partition(":")
        raw = raw.strip()

        if raw:
            container[key] = _scalar(raw)
            continue

        # A key with no value opens either a list or a nested map; the next
        # line says which.
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if following.strip().startswith("- "):
            items = []
            for candidate in lines[index + 1 :]:
                if not candidate.strip().startswith("- "):
                    break
                items.append(_scalar(candidate.strip()[2:]))
            container[key] = items
        else:
            child: dict = {}
            container[key] = child
            child_indent = len(following) - len(following.lstrip()) if following else indent + 2
            stack.append((child_indent, child))

    return data, body


def _scalar(raw: str):
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if raw in {"true", "false"}:
        return raw == "true"
    return raw


class TestNaming:
    def test_catalog_skill_name_does_not_double_the_prefix(self):
        assert catalog_skill_name("travel") == "a2ui-travel"
        assert catalog_skill_name("a2ui-travel") == "a2ui-travel"
        assert catalog_skill_name("forms") == "a2ui-forms"

    def test_alternative_prefix_is_supported(self):
        assert catalog_skill_name("basic", prefix="a2ui-catalog-") == "a2ui-catalog-basic"

    def test_description_falls_back_when_the_catalog_has_none(self, helper):
        skill = build_monolithic_skill(
            format_rules="rules",
            catalog_instructions="catalog",
            examples="",
            description="",
            protocol_version="0.9.1",
            inference_format="express",
            catalogs=["a2ui-travel"],
            catalog_id=helper.catalog_id,
        )
        assert skill.description.startswith("Generates interactive user interface")


class TestFrontmatter:
    @pytest.mark.parametrize(
        "variant,name",
        [
            ("express-monolithic", "a2ui"),
            ("express-modular", "a2ui-core"),
            ("express-modular", "a2ui-travel"),
            ("direct-json-monolithic", "a2ui"),
        ],
    )
    def test_checked_in_skills_have_valid_frontmatter(self, variant, name):
        path = SKILLS / variant / name / "SKILL.md"
        assert path.exists(), f"{path} is missing — run the skill generator"
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))

        assert meta["name"] == name
        assert isinstance(meta["description"], str) and meta["description"]
        assert meta["metadata"]["protocol_version"] == "0.9.1"
        assert body.strip()

    def test_the_model_facing_fields_carry_no_implementation_detail(self):
        """The naming principle, enforced.

        `name` and `description` are the routing signal. Format names, protocol
        versions and schema filenames belong in metadata, where they cost the
        model nothing.
        """
        leaks = ("express", "direct_json", "json", "schema", "sdk", "catalog.json", "0.9")
        for path in sorted(SKILLS.glob("*/*/SKILL.md")):
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            description = meta["description"].lower()
            for leak in leaks:
                assert leak not in description, f"{path}: description leaks '{leak}'"
            assert meta["name"].startswith("a2ui"), path

    def test_metadata_preserves_what_the_description_omits(self):
        meta, _ = parse_frontmatter(
            (SKILLS / "express-monolithic" / "a2ui" / "SKILL.md").read_text(encoding="utf-8")
        )
        metadata = meta["metadata"]
        assert metadata["inference_format"] == "express"
        assert metadata["catalogs"] == ["a2ui-travel"]
        assert metadata["catalog_id"].startswith("http")


class TestBody:
    def test_monolithic_carries_rules_catalog_and_examples(self):
        text = (SKILLS / "express-monolithic" / "a2ui" / "SKILL.md").read_text(encoding="utf-8")
        assert "A2UI Express output contract" in text
        assert "Positional Component Signatures" in text
        assert "FlightOption(" in text
        assert "## Examples" in text

    def test_core_carries_rules_but_no_catalog(self):
        text = (SKILLS / "express-modular" / "a2ui-core" / "SKILL.md").read_text(encoding="utf-8")
        assert "A2UI Express output contract" in text
        assert "FlightOption(" not in text
        assert "a2ui-travel" in text, "core should point at its companion catalog skill"

    def test_catalog_skill_carries_catalog_but_no_rules(self):
        text = (SKILLS / "express-modular" / "a2ui-travel" / "SKILL.md").read_text(encoding="utf-8")
        assert "FlightOption(" in text
        assert "A2UI Express output contract" not in text

    def test_modular_pair_covers_the_monolith(self):
        """Splitting the skill must not lose anything.

        Core plus catalog should contain every component signature the monolith
        does — otherwise the modular shape is quietly a smaller vocabulary.
        """
        mono = (SKILLS / "express-monolithic" / "a2ui" / "SKILL.md").read_text(encoding="utf-8")
        core = (SKILLS / "express-modular" / "a2ui-core" / "SKILL.md").read_text(encoding="utf-8")
        catalog = (SKILLS / "express-modular" / "a2ui-travel" / "SKILL.md").read_text(encoding="utf-8")
        combined = core + catalog

        helper = CatalogHelper.from_path(CATALOG)
        for name in helper.components:
            signature = f"• {name}("
            assert signature in mono, f"{name} missing from the monolithic skill"
            assert signature in combined, f"{name} missing from the modular pair"

    def test_no_skill_ships_scripts(self):
        """These skills are instructions, not executables.

        Nothing here should ever require a runtime on the agent's side.
        """
        for directory in SKILLS.glob("*/*"):
            if not directory.is_dir():
                continue
            files = {p.name for p in directory.iterdir()}
            assert files == {"SKILL.md"}, f"{directory} contains more than SKILL.md: {files}"


class TestSignatures:
    def test_positional_order_matches_the_catalog(self, helper):
        signatures = ExpressFormat().generate_component_signatures(helper)
        line = next(
            line for line in signatures.splitlines() if line.startswith("• FlightOption(")
        )
        args = line[len("• FlightOption(") : -1].split(", ")
        names = [arg.split(" ")[0].rstrip("?") for arg in args]
        assert names[:7] == helper.get_component_properties("FlightOption")[:7]

    def test_required_arguments_are_unmarked_and_optional_ones_carry_a_question_mark(self, helper):
        signatures = ExpressFormat().generate_component_signatures(helper)
        line = next(line for line in signatures.splitlines() if line.startswith("• Text("))
        assert line.startswith("• Text(text, variant?")

    def test_static_properties_are_flagged(self, helper):
        signatures = ExpressFormat().generate_component_signatures(helper)
        line = next(line for line in signatures.splitlines() if line.startswith("• PriceSummary("))
        assert "lines (static only)" in line

    def test_enum_values_are_listed(self, helper):
        signatures = ExpressFormat().generate_component_signatures(helper)
        assert "Must be one of: 'food', 'sight'" in signatures

    def test_direct_json_covers_the_same_components(self, helper):
        block = DirectJsonFormat().generate_catalog_instructions(helper)
        for name in helper.components:
            assert f"• {name}:" in block


class TestExamples:
    def test_titles_come_from_leading_comments(self):
        title, body = split_example('# Inline: flights.\n# Second line.\nroot = Text("x")\n')
        assert title == "Inline: flights. Second line."
        assert body == 'root = Text("x")'

    def test_examples_are_wrapped_in_sentinels(self):
        block = ExpressFormat().generate_examples(load_express_examples(EXAMPLES))
        assert "<a2ui>" in block and "</a2ui>" in block

    def test_compiled_examples_exist_for_every_source(self):
        sources = {p.stem for p in EXAMPLES.glob("*.express")}
        compiled = {p.stem for p in (EXAMPLES / "compiled").glob("*.json")}
        assert sources == compiled, "run: node scripts/build_examples.mjs"

    def test_compiled_examples_are_valid_a2ui(self):
        for path in (EXAMPLES / "compiled").glob("*.json"):
            messages = json.loads(path.read_text(encoding="utf-8"))
            assert isinstance(messages, list) and messages
            for message in messages:
                assert message["version"] == "v0.9.1"


class TestGeneration:
    def test_generating_into_a_fresh_directory_writes_only_skill_files(self, tmp_path):
        written = generate(
            GenerationRequest(
                catalog_path=CATALOG,
                examples_dir=EXAMPLES,
                out_dir=tmp_path,
                catalog_name="a2ui-travel",
                shape="modular",
            )
        )
        assert [skill.name for skill, _ in written] == ["a2ui-core", "a2ui-travel"]
        assert {p.name for p in tmp_path.rglob("*") if p.is_file()} == {"SKILL.md"}

    def test_generation_is_deterministic(self, tmp_path):
        first = generate(
            GenerationRequest(
                catalog_path=CATALOG,
                examples_dir=EXAMPLES,
                out_dir=tmp_path / "a",
                catalog_name="a2ui-travel",
            )
        )
        second = generate(
            GenerationRequest(
                catalog_path=CATALOG,
                examples_dir=EXAMPLES,
                out_dir=tmp_path / "b",
                catalog_name="a2ui-travel",
            )
        )
        assert [s.render() for s, _ in first] == [s.render() for s, _ in second]

    def test_unknown_format_is_rejected_with_the_options(self):
        with pytest.raises(ValueError, match="direct_json"):
            generate(
                GenerationRequest(
                    catalog_path=CATALOG,
                    examples_dir=None,
                    out_dir=pathlib.Path("/tmp"),
                    catalog_name="a2ui-travel",
                    inference_format="yaml",
                )
            )


class TestCoreSkill:
    def test_core_names_its_companions(self):
        skill = build_core_skill(
            format_rules="RULES",
            protocol_version="0.9.1",
            inference_format="express",
            companion_skills=["a2ui-travel", "a2ui-charts"],
        )
        assert "`a2ui-travel`" in skill.body and "`a2ui-charts`" in skill.body
        assert skill.metadata["companion_skills"] == ["a2ui-travel", "a2ui-charts"]

    def test_catalog_skill_declares_its_dependency(self, helper):
        skill = build_catalog_skill(
            catalog_name="a2ui-travel",
            catalog_instructions="SIGS",
            examples="",
            description=helper.description,
            protocol_version="0.9.1",
            inference_format="express",
            catalog_id=helper.catalog_id,
        )
        assert skill.metadata["requires"] == ["a2ui-core"]
