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

from a2ui.inference_formats.express.parser import ExpressParser  # noqa: E402
from a2ui.processor.catalog_config import CatalogConfig  # noqa: E402

from .express import required_properties, whole_payload_validator  # noqa: E402
from .macros import with_macros  # noqa: E402

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

#: Which protocol the catalog declares, and which the wire therefore speaks.
#:
#: Read off the catalog rather than written here. A catalog that does not say
#: is 0.9 by the spec's own default, and a server that disagreed with its
#: catalog about the version would produce messages no renderer accepts — so
#: there is one place to change it, and it is the file a person edits.
CATALOG_VERSION = str(CATALOG_JSON.get("protocolVersion") or "0.9")

#: The same version as the *wire* spells it, which is not how the catalog does.
#:
#: Asked of the SDK rather than written down here. The old comment claimed this
#: was "derived by asking the compiler what it emits rather than hard-coded,
#: which is what makes the upgrade a one-line pin bump instead of a hunt" — and
#: then hard-coded `"v1.0"`. a2ui#3726 dropped that `v` in 0.10.0 and the hunt
#: happened: eighty-three tests red, every one of them the same rejected
#: envelope.
#:
#: So it is derived now. `a2ui.core.schema.v1_0.constants.PROTOCOL_VERSION` is
#: the SDK's own answer to "what goes in the `version` field", and taking it
#: from there means the next rename is a pin bump and nothing else.
def _wire_version(catalog_version: str) -> str:
    try:
        from importlib import import_module

        module = import_module(
            f"a2ui.core.schema.v{catalog_version.replace('.', '_')}.constants"
        )
        return str(module.PROTOCOL_VERSION)
    except (ImportError, AttributeError):
        # A catalog at a version this SDK has no schema module for. The old
        # spelling is the better guess for anything before 1.0, which is the
        # only range that reaches here.
        return f"v{catalog_version}"


PROTOCOL_VERSION = _wire_version(CATALOG_VERSION)


def load_catalog(path: Any = None, version: str | None = None) -> Any:
    """A catalog, loaded and transformed, at the version it declares.

    Public because four other places need a catalog — the example compiler, the
    skill generator and two test modules — and each used to spell the SDK's
    loading incantation itself. That spelling has now changed three times
    (`A2uiCatalog.from_config` is gone in agent-sdk 0.9, `CatalogConfig` moved
    module), and every time it changed, four files had to be found.
    """
    where = str(path or CATALOG_PATH)
    declared = version or CATALOG_VERSION
    config = CatalogConfig.from_path(where, protocol_version=declared)
    return config.transformed_catalog


CATALOG = load_catalog()

#: The catalog as the *model* sees it: every component, plus the macros.
#:
#: Two catalogs, deliberately. `CATALOG` is what a renderer understands and
#: what the surface passes check against. `INFERENCE_CATALOG` is what the model
#: is shown and what its blocks compile against, and it has `Itinerary` in it —
#: a component no renderer will ever receive, because the host expands it on
#: the way out. See `brain/macros.py` for why that trade is worth making.
INFERENCE_CATALOG = with_macros(CATALOG)

VALIDATOR = whole_payload_validator(CATALOG)
COMPONENT_NAMES = frozenset(INFERENCE_CATALOG.components)
#: What each component cannot be drawn without, for explaining a validator no.
REQUIRED_PROPERTIES = required_properties(CATALOG.to_json())


def parser_for(surface_id: str, *also: Any) -> ExpressParser:
    """A compiler for one surface's blocks.

    Takes a *list* of catalogs since 1.0, because a surface may mix them: a
    component or a function call carries its own `catalogId`, and the surface's
    is only the default. `also` is for the surfaces that want more than the
    travel catalog — pass the extra catalogs and the compiler will resolve
    names across all of them.
    """
    return ExpressParser(
        catalogs=[INFERENCE_CATALOG, *also], surface_id=surface_id, version=PROTOCOL_VERSION
    )
