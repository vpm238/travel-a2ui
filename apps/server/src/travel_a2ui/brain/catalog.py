"""The catalog, loaded once, and the things that are derived from it.

Every part of the server that touches A2UI needs the same four facts: which
components exist, what each one cannot be drawn without, how to compile Express
against them, and what to call the catalog on the wire. Loading the catalog is
not free — it reads and resolves a JSON Schema — so it happens once, here, at
import.

These used to live in `doors/interactions.py`, which is where the first code
that needed them was. That made the brain import from a door: `brain/surfaces`
and `brain/contract` both reached into `doors.interactions` for the validator
and the parser, and because the door imports the brain right back, those reaches
had to be written as imports *inside the function bodies* to break the cycle. A
lazy import is a comment saying "the layering is wrong here", and there were
three of them.

So the shared facts moved down to where every layer can see them. The doors keep
what is theirs — which model answers, how many tool rounds are allowed — and the
brain keeps what the brain is made of.
"""

from __future__ import annotations

import warnings
from typing import Any

from .. import ROOT

warnings.filterwarnings("ignore")

from a2ui.inference_formats.experimental.express.parser import ExpressParser  # noqa: E402
from a2ui.schema.catalog import A2uiCatalog, CatalogConfig  # noqa: E402

from .express import required_properties, whole_payload_validator  # noqa: E402

import json  # noqa: E402

CATALOG_PATH = ROOT / "catalogs" / "a2ui-travel" / "catalog.json"
CATALOG_JSON: dict[str, Any] = json.loads(CATALOG_PATH.read_text("utf-8"))

#: What the wire calls this catalog.
#:
#: `$id` rather than `catalogId` because that is what the SDK puts on
#: `createSurface`, and the model has to be told the same string the wire
#: carries. They happen to be identical in this catalog; reading the one the
#: compiler uses means they stay that way if that ever stops being true.
CATALOG_ID = CATALOG_JSON["$id"]

PROTOCOL_VERSION = "v0.9.1"


def _catalog() -> A2uiCatalog:
    config = CatalogConfig.from_path("travel", str(CATALOG_PATH))
    return A2uiCatalog.from_config(config, version="0.9.1")


CATALOG = _catalog()

VALIDATOR = whole_payload_validator(CATALOG)
COMPONENT_NAMES = frozenset(CATALOG.catalog_schema["components"])
#: What each component cannot be drawn without, for explaining a validator no.
REQUIRED_PROPERTIES = required_properties(CATALOG.catalog_schema)


def parser_for(surface_id: str) -> ExpressParser:
    """A compiler for one surface's blocks."""
    return ExpressParser(catalog=CATALOG, surface_id=surface_id, version=PROTOCOL_VERSION)
