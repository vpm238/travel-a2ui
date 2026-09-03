"""Assembles A2UI skills.

## The naming principle

A skill's `name` and `description` are what an agent sees during skill
discovery, and they are all it sees before deciding whether to load the thing.
So they describe a **capability** — "generates interactive user interfaces" —
and never an implementation. Which inference format the SDK compiles, which
protocol version is on the wire, which schema file the signatures came from:
none of that helps a model route a request, and all of it crowds out the words
that do.

Those details are not thrown away. They go in `metadata`, where SDKs, platform
indexers and humans debugging a bad render can read them, and where they cost
the model nothing.

## The two shapes

**Monolithic** — one skill, `a2ui`, carrying the format rules, the whole
catalog and the examples. Simplest to install; every turn pays for every
component.

**Modular** — `a2ui-core` carries the format rules that never change, and one
`a2ui-<catalog>` skill per catalog carries that catalog's signatures and
examples. An agent working on travel loads core plus travel and never pays for
the charting catalog. This is the shape that scales past one domain.
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Any, Optional

DEFAULT_DESCRIPTION = "Generates interactive user interface components for user requests."

CORE_DESCRIPTION = (
    "Core rules for generating user interfaces. Load alongside a UI component "
    "skill whenever a response would be clearer as an interface than as text."
)

MONOLITHIC_NAME = "a2ui"
CORE_NAME = "a2ui-core"


def catalog_skill_name(catalog_name: str, prefix: str = "a2ui-") -> str:
    """Derives a catalog skill's name.

    `travel` and `a2ui-travel` both become `a2ui-travel`: catalogs are often
    already namespaced, and `a2ui-a2ui-travel` helps nobody.
    """
    short = catalog_name.strip()
    for lead in ("a2ui-", "a2ui_"):
        if short.lower().startswith(lead):
            short = short[len(lead) :]
            break
    return f"{prefix}{short}"


def _yaml_scalar(value: Any) -> str:
    """Renders a scalar for frontmatter, quoting anything YAML might reinterpret."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    needs_quotes = (
        text == ""
        or text[0] in "&*?|-<>=!%@`{[\"'"
        or ": " in text
        or text.endswith(":")
        or "#" in text
        or text.strip() != text
        or text.lower() in {"true", "false", "null", "yes", "no", "on", "off"}
        # Anything starting with a digit gets quoted, so `0.9.1` stays a version
        # string and does not depend on a YAML parser's opinion about it.
        or text[0].isdigit()
        or _looks_numeric(text)
    )
    if needs_quotes:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _looks_numeric(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _render_metadata(metadata: dict[str, Any], indent: str = "  ") -> list[str]:
    lines: list[str] = []
    for key, value in metadata.items():
        if isinstance(value, (list, tuple)):
            lines.append(f"{indent}{key}:")
            for item in value:
                lines.append(f"{indent}  - {_yaml_scalar(item)}")
        elif isinstance(value, dict):
            lines.append(f"{indent}{key}:")
            lines.extend(_render_metadata(value, indent + "  "))
        else:
            lines.append(f"{indent}{key}: {_yaml_scalar(value)}")
    return lines


@dataclasses.dataclass
class Skill:
    """One generated skill: a directory name, frontmatter, and a body."""

    name: str
    description: str
    metadata: dict[str, Any]
    body: str

    def render(self) -> str:
        lines = ["---", f"name: {_yaml_scalar(self.name)}", f"description: {_yaml_scalar(self.description)}"]
        if self.metadata:
            lines.append("metadata:")
            lines.extend(_render_metadata(self.metadata))
        lines.append("---")
        return "\n".join(lines) + "\n\n" + self.body.strip() + "\n"

    def write(self, root: pathlib.Path) -> pathlib.Path:
        directory = root / self.name
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "SKILL.md"
        target.write_text(self.render(), encoding="utf-8")
        return target


def _join(*sections: Optional[str]) -> str:
    return "\n\n".join(section.strip() for section in sections if section and section.strip())


def build_monolithic_skill(
    *,
    format_rules: str,
    catalog_instructions: str,
    examples: str,
    description: str,
    protocol_version: str,
    inference_format: str,
    catalogs: list[str],
    catalog_id: str,
) -> Skill:
    """One skill that carries everything: rules, catalog, examples."""
    return Skill(
        name=MONOLITHIC_NAME,
        description=description or DEFAULT_DESCRIPTION,
        metadata={
            "protocol_version": protocol_version,
            "inference_format": inference_format,
            "catalogs": catalogs,
            "catalog_id": catalog_id,
        },
        body=_join(format_rules, catalog_instructions, examples),
    )


def build_core_skill(
    *,
    format_rules: str,
    protocol_version: str,
    inference_format: str,
    companion_skills: list[str],
    description: str = CORE_DESCRIPTION,
) -> Skill:
    """The format rules on their own — everything that does not vary by catalog."""
    companions = ", ".join(f"`{name}`" for name in companion_skills)
    pairing = (
        "\n\n## Component catalogs\n\n"
        "This skill defines the notation, not the components. The components you "
        f"may use come from a companion catalog skill ({companions}). Load one "
        "alongside this skill; without it you have grammar and no vocabulary."
        if companion_skills
        else ""
    )
    return Skill(
        name=CORE_NAME,
        description=description,
        metadata={
            "protocol_version": protocol_version,
            "inference_format": inference_format,
            "companion_skills": companion_skills,
        },
        body=format_rules.strip() + pairing,
    )


def build_catalog_skill(
    *,
    catalog_name: str,
    catalog_instructions: str,
    examples: str,
    description: str,
    protocol_version: str,
    inference_format: str,
    catalog_id: str,
    prefix: str = "a2ui-",
    requires: str = CORE_NAME,
) -> Skill:
    """One catalog's components and examples, to be paired with `a2ui-core`."""
    return Skill(
        name=catalog_skill_name(catalog_name, prefix),
        description=description or DEFAULT_DESCRIPTION,
        metadata={
            "protocol_version": protocol_version,
            "inference_format": inference_format,
            "catalog": catalog_name,
            "catalog_id": catalog_id,
            "requires": [requires],
        },
        body=_join(catalog_instructions, examples),
    )
