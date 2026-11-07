"""One turn of the conversation.

  `press.py`   the request, the press, and the sentence it becomes
  `turn.py`    the model, the stream, the tool loop, the receipt
  `panels.py`  the first draw of the panel, when a turn ends without one
  `warmup.py`  before all of it: the conversation, started while the page loads

The catalog and the A2UI processor are `brain/catalog.py`; the model choices
are `doors/settings.py`.
"""

from __future__ import annotations

from ...brain.catalog import CATALOG, CATALOG_ID, CATALOG_JSON, CATALOG_PATH, PROTOCOL_VERSION
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
from .press import (
    SurfaceAction,
    TurnRequest,
    TurnResult,
    _leg_pressed,
    _party_paths,
    describe_action,
)
from .turn import run_turn, run_turn_collected
from .warmup import WarmRequest, warm

__all__ = [
    "CATALOG",
    "CATALOG_ID",
    "CATALOG_JSON",
    "CATALOG_PATH",
    "DEFAULT_EFFORT",
    "DEFAULT_MODEL",
    "FALLBACK_MODEL",
    "MAX_TOOL_ROUNDS",
    "PANEL_EFFORT",
    "PANEL_MODEL",
    "PANEL_REQUEST",
    "PROTOCOL_VERSION",
    "SurfaceAction",
    "TurnRequest",
    "TurnResult",
    "WarmRequest",
    "_leg_pressed",
    "_party_paths",
    "_today",
    "describe_action",
    "run_turn",
    "run_turn_collected",
    "warm",
]
