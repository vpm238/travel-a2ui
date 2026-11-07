"""The published skills are what the model is taught, generated, not edited.

`scripts/build_skills.py` writes them with `SkillGenerator(PROCESSOR.format)`,
the same processor that writes the prompt snippet and parses the model's
output. These hold the three together.
"""

from __future__ import annotations

import sys

from travel_a2ui import ROOT  # noqa: E402
from travel_a2ui.brain.catalog import PROCESSOR  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import build_skills  # noqa: E402

SKILLS = ROOT / "skills" / build_skills.VARIANT


def _body(markdown: str) -> str:
    return markdown.split("\n---\n", 1)[1].strip() if markdown.startswith("---") else markdown.strip()


def test_the_skills_on_disk_are_the_generators() -> None:
    for skill in build_skills.skills():
        on_disk = (SKILLS / skill.filename).read_text("utf-8")
        assert _body(on_disk) == _body(skill.to_markdown()), f"{skill.filename} is stale"


def test_the_model_is_taught_what_the_skills_say() -> None:
    snippet = PROCESSOR.prompt_snippet
    for skill in build_skills.skills():
        for line in _body(skill.to_markdown()).splitlines():
            if line.startswith("• "):
                assert line in snippet, f"{skill.name} documents a signature the model is not shown: {line}"


def test_each_skill_is_instructions_only() -> None:
    for directory in SKILLS.iterdir():
        assert sorted(path.name for path in directory.iterdir()) == ["SKILL.md"], directory


def test_the_skills_name_the_protocol_they_teach() -> None:
    for path in SKILLS.rglob("SKILL.md"):
        assert "protocol_version: '1.0'" in path.read_text("utf-8")
