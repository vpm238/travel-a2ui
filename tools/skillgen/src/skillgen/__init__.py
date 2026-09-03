"""Generate A2UI skills from a component catalog.

The public surface mirrors the shape the generation rules are written in:

    from skillgen import CatalogHelper, ExpressFormat, build_monolithic_skill

    helper = CatalogHelper.from_path("catalogs/a2ui-travel/catalog.json")
    fmt = ExpressFormat()
    skill = build_monolithic_skill(
        format_rules=fmt.generate_base_rules(),
        catalog_instructions=fmt.generate_catalog_instructions(helper),
        examples=fmt.generate_examples(examples),
        description=helper.description,
        protocol_version="0.9.1",
        inference_format=fmt.id,
        catalogs=["a2ui-travel"],
        catalog_id=helper.catalog_id,
    )
"""

from .catalog import CatalogHelper
from .formats.direct_json import DirectJsonFormat
from .formats.express import ExpressFormat, split_example
from .generator import (
    FORMATS,
    SHAPES,
    GenerationRequest,
    generate,
    generate_all,
    load_express_examples,
    load_json_examples,
)
from .skill import (
    CORE_NAME,
    MONOLITHIC_NAME,
    Skill,
    build_catalog_skill,
    build_core_skill,
    build_monolithic_skill,
    catalog_skill_name,
)

__all__ = [
    "CORE_NAME",
    "FORMATS",
    "GenerationRequest",
    "MONOLITHIC_NAME",
    "SHAPES",
    "CatalogHelper",
    "DirectJsonFormat",
    "ExpressFormat",
    "Skill",
    "build_catalog_skill",
    "build_core_skill",
    "build_monolithic_skill",
    "catalog_skill_name",
    "generate",
    "generate_all",
    "load_express_examples",
    "load_json_examples",
    "split_example",
]
