"""Turns a catalog plus a set of examples into skill variants on disk."""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re
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
    #: Components the agent is allowed to draw. ``None`` means the whole catalog.
    #: Narrowing this prunes the *prompt*, never a renderer — see `with_pruning`.
    allowed_components: tuple[str, ...] | None = None
    #: Catalog functions the agent is allowed to call. ``None`` means all of them.
    allowed_functions: tuple[str, ...] | None = None

    @property
    def variant(self) -> str:
        """The output directory name: `<format>-<shape>`.

        Variants live in sibling directories rather than under different skill
        names, so that a monolithic Express `a2ui` and a monolithic JSON `a2ui`
        can both exist without either one renaming itself to say which it is.
        The skill name stays clean; the directory carries the variant.
        """
        return f"{self.inference_format.replace('_', '-')}-{self.shape}"


#: `Name(` at the head of a call — how a component is spelled in Express.
_CALL = re.compile(r"\b([A-Z][A-Za-z0-9]*)\s*\(")

#: `?required`, `?email("…")` — how a check rule is spelled.
_RULE = re.compile(r"\?([a-z][A-Za-z0-9]*)")

#: `formatCurrency(` — a catalog function called for its value.
_FUNCTION = re.compile(r"\b([a-z][A-Za-z0-9]*)\s*\(")


@dataclasses.dataclass(frozen=True)
class Vocabulary:
    """What the pruned catalog still offers, against what it ever offered.

    Both halves are needed. `allowed` alone cannot tell a pruned component from
    a name that was never in this catalog — `Event(`, `_template(`, a component
    borrowed from another catalog — and rejecting those would throw away every
    example.
    """

    allowed_components: set[str]
    known_components: set[str]
    allowed_functions: set[str]
    known_functions: set[str]


def uses_only(source: str, vocabulary: Vocabulary) -> bool:
    """True when everything the example calls survived pruning.

    Components and functions both: an example teaching `?required` after the
    validators were pruned is an example teaching a call the prompt no longer
    documents, which is the same failure whichever case the name starts with.
    """
    for name in _CALL.findall(source):
        if name in vocabulary.known_components and name not in vocabulary.allowed_components:
            return False
    for name in _RULE.findall(source) + _FUNCTION.findall(source):
        if name in vocabulary.known_functions and name not in vocabulary.allowed_functions:
            return False
    return True


def load_express_examples(
    directory: pathlib.Path | None,
    vocabulary: Vocabulary | None = None,
) -> list[tuple[str, str]]:
    if directory is None or not directory.is_dir():
        return []
    examples: list[tuple[str, str]] = []
    for path in sorted(directory.glob("*.express")):
        source = path.read_text(encoding="utf-8")
        # An example that draws a pruned component teaches the model to call
        # something the prompt no longer documents.
        if vocabulary is not None and not uses_only(source, vocabulary):
            continue
        examples.append(split_example(source))
    return examples


def load_json_examples(
    directory: pathlib.Path | None,
    vocabulary: Vocabulary | None = None,
) -> list[tuple[str, Any]]:
    """Pairs each compiled example with the title from its Express source."""
    if directory is None or not directory.is_dir():
        return []
    compiled = directory / "compiled"
    if not compiled.is_dir():
        return []
    examples: list[tuple[str, Any]] = []
    for path in sorted(compiled.glob("*.json")):
        source = directory / f"{path.stem}.express"
        text = source.read_text(encoding="utf-8") if source.exists() else ""
        if vocabulary is not None and text and not uses_only(text, vocabulary):
            continue
        title = split_example(text)[0] if text else path.stem
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
    known_components = set(helper.components)
    known_functions = set(helper.functions)

    # Pruning happens here, before a single signature is rendered, so the
    # savings land in every downstream artifact at once: the system prompt, the
    # `get_a2ui_component_reference` contract, and the examples.
    vocabulary: Vocabulary | None = None
    if request.allowed_components is not None or request.allowed_functions is not None:
        helper = helper.with_pruning(
            allowed_components=request.allowed_components,
            allowed_functions=request.allowed_functions,
        )
        vocabulary = Vocabulary(
            allowed_components=set(helper.components),
            known_components=known_components,
            allowed_functions=set(helper.functions),
            known_functions=known_functions,
        )

    fmt = FORMATS[request.inference_format]()

    # The pruned helper, so the grammar does not teach a syntax whose operands
    # were all pruned away.
    base_rules = (
        fmt.generate_base_rules(helper)
        if request.inference_format == "express"
        else fmt.generate_base_rules()
    )
    catalog_instructions = fmt.generate_catalog_instructions(helper)

    examples_block = ""
    if request.include_examples:
        if request.inference_format == "express":
            examples_block = fmt.generate_examples(
                load_express_examples(request.examples_dir, vocabulary)
            )
        else:
            examples_block = fmt.generate_examples(
                load_json_examples(request.examples_dir, vocabulary)
            )

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
