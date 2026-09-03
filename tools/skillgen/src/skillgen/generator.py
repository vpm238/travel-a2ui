"""Turns a catalog plus a set of examples into skill variants on disk."""

from __future__ import annotations

import dataclasses
import json
import pathlib
from typing import Any, Iterable

from .catalog import CatalogHelper
from .formats.direct_json import DirectJsonFormat
from .formats.express import ExpressFormat, split_example
from .skill import Skill, build_catalog_skill, build_core_skill, build_monolithic_skill

FORMATS = {"express": ExpressFormat, "direct_json": DirectJsonFormat}
SHAPES = ("monolithic", "modular")


@dataclasses.dataclass
class GenerationRequest:
    catalog_path: pathlib.Path
    examples_dir: pathlib.Path | None
    out_dir: pathlib.Path
    catalog_name: str
    protocol_version: str = "0.9.1"
    inference_format: str = "express"
    shape: str = "monolithic"
    catalog_prefix: str = "a2ui-"
    include_examples: bool = True

    @property
    def variant(self) -> str:
        """The output directory name: `<format>-<shape>`.

        Variants live in sibling directories rather than under different skill
        names, so that a monolithic Express `a2ui` and a monolithic JSON `a2ui`
        can both exist without either one renaming itself to say which it is.
        The skill name stays clean; the directory carries the variant.
        """
        return f"{self.inference_format.replace('_', '-')}-{self.shape}"


def load_express_examples(directory: pathlib.Path | None) -> list[tuple[str, str]]:
    if directory is None or not directory.is_dir():
        return []
    examples: list[tuple[str, str]] = []
    for path in sorted(directory.glob("*.express")):
        examples.append(split_example(path.read_text(encoding="utf-8")))
    return examples


def load_json_examples(directory: pathlib.Path | None) -> list[tuple[str, Any]]:
    """Pairs each compiled example with the title from its Express source."""
    if directory is None or not directory.is_dir():
        return []
    compiled = directory / "compiled"
    if not compiled.is_dir():
        return []
    examples: list[tuple[str, Any]] = []
    for path in sorted(compiled.glob("*.json")):
        source = directory / f"{path.stem}.express"
        title = split_example(source.read_text(encoding="utf-8"))[0] if source.exists() else path.stem
        examples.append((title, json.loads(path.read_text(encoding="utf-8"))))
    return examples


def generate(request: GenerationRequest) -> list[tuple[Skill, pathlib.Path]]:
    """Generates the skills for one (format, shape) variant and writes them."""
    if request.inference_format not in FORMATS:
        raise ValueError(
            f"Unknown inference format '{request.inference_format}'. "
            f"Choose from: {', '.join(sorted(FORMATS))}."
        )
    if request.shape not in SHAPES:
        raise ValueError(
            f"Unknown skill shape '{request.shape}'. Choose from: {', '.join(SHAPES)}."
        )

    helper = CatalogHelper.from_path(request.catalog_path)
    fmt = FORMATS[request.inference_format]()

    base_rules = fmt.generate_base_rules()
    catalog_instructions = fmt.generate_catalog_instructions(helper)

    examples_block = ""
    if request.include_examples:
        if request.inference_format == "express":
            examples_block = fmt.generate_examples(load_express_examples(request.examples_dir))
        else:
            examples_block = fmt.generate_examples(load_json_examples(request.examples_dir))

    root = request.out_dir / request.variant
    skills: list[Skill] = []

    if request.shape == "monolithic":
        skills.append(
            build_monolithic_skill(
                format_rules=base_rules,
                catalog_instructions=catalog_instructions,
                examples=examples_block,
                description=helper.description,
                protocol_version=request.protocol_version,
                inference_format=request.inference_format,
                catalogs=[request.catalog_name],
                catalog_id=helper.catalog_id,
            )
        )
    else:
        catalog_skill = build_catalog_skill(
            catalog_name=request.catalog_name,
            catalog_instructions=catalog_instructions,
            examples=examples_block,
            description=helper.description,
            protocol_version=request.protocol_version,
            inference_format=request.inference_format,
            catalog_id=helper.catalog_id,
            prefix=request.catalog_prefix,
        )
        skills.append(
            build_core_skill(
                format_rules=base_rules,
                protocol_version=request.protocol_version,
                inference_format=request.inference_format,
                companion_skills=[catalog_skill.name],
            )
        )
        skills.append(catalog_skill)

    return [(skill, skill.write(root)) for skill in skills]


def generate_all(
    *,
    catalog_path: pathlib.Path,
    examples_dir: pathlib.Path | None,
    out_dir: pathlib.Path,
    catalog_name: str,
    protocol_version: str,
    variants: Iterable[tuple[str, str]],
) -> list[tuple[Skill, pathlib.Path]]:
    """Generates several (format, shape) variants in one pass."""
    written: list[tuple[Skill, pathlib.Path]] = []
    for inference_format, shape in variants:
        written.extend(
            generate(
                GenerationRequest(
                    catalog_path=catalog_path,
                    examples_dir=examples_dir,
                    out_dir=out_dir,
                    catalog_name=catalog_name,
                    protocol_version=protocol_version,
                    inference_format=inference_format,
                    shape=shape,
                )
            )
        )
    return written
