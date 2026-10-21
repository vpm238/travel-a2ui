"""The agent's tools.

A deliberate split runs through this package, and it is the whole architectural
idea of the project:

    **Tools return data. The skill turns data into UI.**

No tool here returns A2UI. `search_flights` returns flights. The model reads
them and writes Express, because deciding *how* to present five flights — which
to lead with, what to say about the stopover, whether this is a moment for a
price summary — is a judgement call, and judgement is what the model is for. A
tool returning pre-rendered cards moves that decision into this package, where
it would be frozen and wrong half the time.

The one exception is `save_trip`, which writes rather than reads, because the
traveller's choices have to outlive the turn that made them.

Four files, in the order a call goes through them:

  `contracts`  what the model may call, and what a tool is handed when it does
  `answers`    turning what a provider found into something worth reading
  `share`      the one output that is a page rather than a surface
  `run`        the switch: one branch per tool name

The contracts themselves are in `data/tools.json`, shared with the TypeScript
implementation while that still exists. They are prompt engineering as much as
schema, and a retyped description is a different agent.
"""

from __future__ import annotations

from .contracts import (  # noqa: F401 — re-exported: this package is one module to its callers
    DATA_TOOL_NAMES,
    GROUNDING,
    REFUSABLE,
    TOOLS,
    ToolContext,
    gemini_tools,
    grounding_tools,
    is_data_tool,
    _ROOT,
)
from .answers import (  # noqa: F401 — re-exported: this package is one module to its callers
    _SYMBOLS,
    _cannot,
    _day_text,
    _effective_trip,
    _estimate,
    _money_text,
    _needs_input,
    _nights_between,
    _num,
    _priced_for,
    _route_note,
    _str,
    _trip_currency,
)
from .share import (  # noqa: F401 — re-exported: this package is one module to its callers
    FIXTURE_NOTE,
    _share_page,
)
from .run import (  # noqa: F401 — re-exported: this package is one module to its callers
    run_tool,
    _run,
)
