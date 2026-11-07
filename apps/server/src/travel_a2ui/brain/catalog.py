"""The catalog, and the A2UI processor that reads what the model writes.

One configuration, used everywhere the model meets A2UI: the processor that
writes the prompt snippet and parses the model's output at runtime, and the
skill generator at build time (`scripts/build_skills.py`). The two cannot
drift because they are built from the same `model_catalogs()` and examples.

    CATALOG            what a renderer draws: the whole travel catalog
    model_catalogs()   what the model is offered: pruned to the components
                       this agent draws (`agent-components.json`), plus macros
    processor_for()    an `A2uiRequestProcessor` over those catalogs, negotiated
                       against the renderer's capabilities

Everything the model writes is parsed and validated by that processor. After
the macros are expanded, the result is validated again against `CATALOG` by a
`RendererState` that mirrors the renderer (`brain/ui.py`).
"""

from __future__ import annotations

import json
from typing import Any

from a2ui.catalog_transformers import ComponentPruningTransformer, FunctionPruningTransformer
from a2ui.core import to_protocol_version
from a2ui.inference_formats import ExpressFormatFactory, to_message_models
from a2ui.processor import A2uiRequestProcessor, CatalogConfig
from a2ui.utils import RendererState, resolve_catalogs

from .. import ROOT
from .macros import with_macros

CATALOG_DIR = ROOT / "catalogs" / "a2ui-travel"
CATALOG_PATH = CATALOG_DIR / "catalog.json"
CATALOG_JSON: dict[str, Any] = json.loads(CATALOG_PATH.read_text("utf-8"))
CATALOG_ID: str = CATALOG_JSON["catalogId"]

#: The protocol version this catalog declares, as the `version` field spells it.
PROTOCOL_VERSION: str = to_protocol_version("1.0").value
assert str(CATALOG_JSON["protocolVersion"]).startswith(PROTOCOL_VERSION), (
    f"the catalog declares {CATALOG_JSON['protocolVersion']}, the SDK speaks {PROTOCOL_VERSION}"
)

#: What a renderer draws. Every message that leaves the server is valid here.
CATALOG = CatalogConfig.from_path(str(CATALOG_PATH), protocol_version=PROTOCOL_VERSION).transformed_catalog

#: Which components and functions the model is offered (`agent-components.json`).
AGENT_COMPONENTS: dict[str, Any] = json.loads((CATALOG_DIR / "agent-components.json").read_text("utf-8"))

#: The message types the model may write. Function calls to and from the
#: renderer are not part of this app.
ALLOWED_MESSAGES = ["createSurface", "updateComponents", "updateDataModel", "deleteSurface"]

#: The catalog as the agent registers it: pruned for the model.
MODEL_CONFIG = CatalogConfig.from_path(
    str(CATALOG_PATH),
    transformers=[
        ComponentPruningTransformer(AGENT_COMPONENTS["allowedComponents"]),
        FunctionPruningTransformer(AGENT_COMPONENTS["allowedFunctions"]),
    ],
    protocol_version=PROTOCOL_VERSION,
)


def _load_examples() -> list[list[dict[str, Any]]]:
    """The worked examples, one turn per file, written as A2UI JSON.

    The SDK decompiles them into the inference format for the prompt, so they
    are written once, in the wire format, and checked against the catalog.
    """
    turns = []
    for path in sorted((CATALOG_DIR / "examples").glob("*.json")):
        turn = json.loads(path.read_text("utf-8"))
        turns.append(turn["messages"] if isinstance(turn, dict) else turn)
    return turns


EXAMPLES = _load_examples()


def negotiate(capabilities: Any = None) -> list[Any]:
    """The catalogs this conversation uses, for the renderer's capabilities.

    Without capabilities, every catalog the agent registered. Raises the SDK's
    `A2uiCatalogError` when the renderer supports none of them.
    """
    return resolve_catalogs([MODEL_CONFIG], capabilities)


def model_catalogs(capabilities: Any = None) -> list[Any]:
    """What the model is offered: the negotiated catalogs, plus the macros."""
    return [with_macros(catalog) for catalog in negotiate(capabilities)]


def processor_for(surface_id: str, capabilities: Any = None) -> A2uiRequestProcessor:
    """The processor for one turn, drawing into `surface_id` by default.

    The Express format fixes a default surface when it is created, so a turn
    gets a processor of its own; a block can still address another surface
    with `surface("sidebar")`.
    """
    return A2uiRequestProcessor(
        model_catalogs(capabilities),
        examples=EXAMPLES,
        format_factory=ExpressFormatFactory(
            surface_id=surface_id, allowed_messages=ALLOWED_MESSAGES, version=PROTOCOL_VERSION
        ),
    )


#: A processor with no surface of its own, for the prompt and the skills: the
#: snippet does not depend on the surface.
PROCESSOR = processor_for("main")


def renderer_state() -> RendererState:
    """An empty mirror of a renderer that holds this catalog."""
    return RendererState([CATALOG])


_WIRE_PROCESSOR: A2uiRequestProcessor | None = None


def wire_processor() -> A2uiRequestProcessor:
    """A processor over the whole catalog, with no macros: what a renderer holds.

    For the Wire view and the Catalog view, which show every component, not
    only the ones this agent is offered.
    """
    global _WIRE_PROCESSOR
    if _WIRE_PROCESSOR is None:
        _WIRE_PROCESSOR = A2uiRequestProcessor(
            [CATALOG],
            format_factory=ExpressFormatFactory(allowed_messages=ALLOWED_MESSAGES, version=PROTOCOL_VERSION),
        )
    return _WIRE_PROCESSOR


def decompile(messages: list[dict[str, Any]]) -> str:
    """Wire messages as Express, over the whole catalog (the Wire view)."""
    return wire_processor().parser.decompile(to_message_models(messages))
