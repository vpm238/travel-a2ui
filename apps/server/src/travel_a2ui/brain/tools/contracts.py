"""What the model may call, and what it is handed when it does.

The contracts themselves are in `data/tools.json`, shared with the TypeScript
implementation while that still exists. They are prompt engineering as much as
schema — a retyped description is a different agent — so they are read, never
restated here.

`ToolContext` is the other half: the trip a tool may write to, the provider it
looks things up through, and the date it is allowed to think it is. A tool that
reached for any of those itself would be a tool that cannot be run twice in a
test.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable

from ... import ROOT
from .. import trip as model

_ROOT = ROOT
TOOLS: list[dict[str, Any]] = json.loads(
    (_ROOT / "data" / "tools.json").read_text("utf-8")
)["tools"]

#: Fields a surface may not quietly change, even by pressing a button.
#:
#: `save_trip` validates; a button press used to not, so a picker sending
#: 20 Apr → 12 Apr priced four flights against negative nights. The table lives
#: in the model, with the sieve that applies it.
REFUSABLE = model.REFUSABLE


@dataclass
class ToolContext:
    """What a tool may read and write for the turn it is part of."""

    #: The trip so far, readable and writable across turns.
    trip: dict[str, Any]
    #: Where travel data comes from. On the context rather than imported,
    #: because it is a property of the deployment — fixtures by default, live
    #: inventory where a credential is set.
    provider: TravelProvider
    #: Called with a patch when a tool changes the trip.
    save: Callable[[dict[str, Any]], None] = lambda patch: None
    #: The day this turn happens on, as `YYYY-MM-DD`. Defaulted from the clock,
    #: because every caller in the app means now. It is here at all because
    #: `save_trip` refuses a start date in the past, so a tool reading the clock
    #: directly has behaviour that depends on the day it runs — and a golden of
    #: that would rot overnight.
    today: str | None = None

    def day(self) -> str:
        return self.today or _dt.date.today().isoformat()


def gemini_tools() -> list[dict[str, Any]]:
    """The tools in the shape the Interactions API wants them.

    Function declarations only. `voice_tools` reads `name`, `description` and
    `parameters` off every entry here, so a built-in tool — which has none of
    them — belongs in `grounding_tools` instead, not in this list.

    `get_trip` is not offered. This model is handed the whole trip in its system
    prompt, under "The trip so far", so calling it buys nothing — and it costs a
    round: the loop stops, sends the results back, and waits for the model to
    start again. A traced turn spent one of its three rounds, about eight
    seconds, reading back something it was already looking at.

    It still exists as a tool, and `run_tool` still answers it: a caller that
    does not get the trip in a prompt has no other way to see it.
    """
    return [
        {
            "type": "function",
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        }
        for tool in TOOLS
        if tool["name"] != "get_trip"
    ]


#: Whether the model may look things up on the open web.
#:
#: On by default, off with `GROUNDING=off` — worth a switch because it is the
#: one thing here that reaches outside the process. A deployment that must be
#: reproducible, or one behind a network policy that forbids it, should be able
#: to say so without editing code.
GROUNDING = os.environ.get("GROUNDING", "on").strip().lower() not in {"off", "0", "false"}


#: Tools a host model may call for data rather than for a surface.
#:
#: Named as a set rather than "everything not `show_`" because a tool that
#: quietly became callable because of how its name was spelled would be a change
#: nobody decided to make.
DATA_TOOL_NAMES = frozenset(tool["name"] for tool in TOOLS)


def is_data_tool(name: str) -> bool:
    return name in DATA_TOOL_NAMES


def grounding_tools() -> list[dict[str, Any]]:
    """Google's own tools, for the parts of a trip that are facts about the world.

    The eight functions above answer with fixtures: a fare, a nightly rate, a
    list of neighbourhoods, all generated and all labelled as generated. That is
    honest for prices — nobody should trust a fare from a demo — but it is a
    poor answer for the half of planning that is not a price. Whether a place is
    worth three days or one, what is closed in April, whether the festival is
    the week they arrive: those are facts, they change, and no fixture will ever
    have them.

    So the model gets Search and URL context alongside its own tools, and the
    two do different jobs. Gemini 3 supports the combination; on a model that
    does not, this is the list to leave empty.

    These are *not* given to the voice session. The Live API takes a different
    tool shape, and the failure mode for getting it wrong is a setup frame
    rejected whole, with nothing naming the tool that caused it.
    """
    if not GROUNDING:
        return []
    return [{"type": "google_search"}, {"type": "url_context"}]
