"""One turn of the conversation.

The shape of a turn, in order:

  1. Take what the traveller set on screen and put it in the trip — *before*
     asking the model anything, because a value they typed is a fact and should
     not depend on the model noticing and calling `save_trip`.
  2. Turn what they pressed into a sentence the model can read.
  3. Ask the model, streaming. Split prose from A2UI as it arrives, so the
     surface paints while the model is still typing.
  4. When it calls a tool: draw the shape of the answer first, run the tool,
     then fill the shape. The screen is busy for the whole wait rather than
     empty for it.
  5. Bring the standing panels up to date, and rebuild them if the decisions
     changed shape enough to need different controls.

Everything the browser used to decide for itself is in here now. It used to
hold a list of trip field names, watch them, and send a prose prompt asking for
a new panel — a private protocol composed in a client, which meant a Flutter or
second renderer that did not send it simply never got a panel.

Those five steps are four files, and the numbers say which:

  `press.py`   1 and 2 — the request, the press, and the sentence it becomes
  `turn.py`    3 and 4 — the model, the stream, the tool loop, the receipt
  `panels.py`  5       — the standing surfaces, and when they are worth redrawing
  `warmup.py`  before all of it — the conversation, started while the page loads

This module is the door's address book: everything the rest of the server asks
`doors.interactions` for still answers here, whichever file it now lives in.
The catalog and the model choices are not in it at all — they are
`brain/catalog.py` and `doors/settings.py`, so the brain never imports a door
and one door never imports another.
"""

from __future__ import annotations

from ...brain.catalog import (
    CATALOG,
    CATALOG_ID,
    CATALOG_JSON,
    CATALOG_PATH,
    COMPONENT_NAMES,
    PROTOCOL_VERSION,
    REQUIRED_PROPERTIES,
    VALIDATOR,
    parser_for,
)
from ..settings import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    FALLBACK_MODEL,
    MAX_TOOL_ROUNDS,
    PANEL_EFFORT,
    PANEL_MODEL,
    PANEL_REQUEST,
    _today,
)
from .panels import _rebuild_panels
from .press import (
    REFUSABLE,
    SurfaceAction,
    TurnRequest,
    TurnResult,
    _commit,
    _leg_pressed,
    _party_paths,
    describe_action,
)
from .turn import run_turn, run_turn_collected
from .warmup import WarmRequest, warm

#: The names the catalog used to have when it lived in this module. Kept
#: because this is where the rest of the server and every test has always asked
#: for them, and renaming at the call sites would be churn in every door at once
#: for no reading gained.
_CATALOG = CATALOG
_VALIDATOR = VALIDATOR
_parser = parser_for

__all__ = [
    "CATALOG",
    "CATALOG_ID",
    "CATALOG_JSON",
    "CATALOG_PATH",
    "COMPONENT_NAMES",
    "DEFAULT_EFFORT",
    "DEFAULT_MODEL",
    "FALLBACK_MODEL",
    "MAX_TOOL_ROUNDS",
    "PANEL_EFFORT",
    "PANEL_MODEL",
    "PANEL_REQUEST",
    "PROTOCOL_VERSION",
    "REFUSABLE",
    "REQUIRED_PROPERTIES",
    "SurfaceAction",
    "TurnRequest",
    "TurnResult",
    "VALIDATOR",
    "WarmRequest",
    "_CATALOG",
    "_VALIDATOR",
    "_commit",
    "_leg_pressed",
    "_parser",
    "_party_paths",
    "_rebuild_panels",
    "_today",
    "describe_action",
    "parser_for",
    "run_turn",
    "run_turn_collected",
    "warm",
]
