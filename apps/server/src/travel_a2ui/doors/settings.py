"""The choices a door makes before the agent is asked anything.

Which model answers, how hard it thinks, who answers when it is busy, which
model draws the panel, and what a panel turn asks for. None of it is about a
particular door, and all of it has to be the same in every door: a traveller
who switches from typing to talking should not get a different agent, so both
doors import these rather than naming their own.

`_today` is here for the same reason: both doors are told what day it is by the
client, and both have to read that the same sceptical way.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Any

#: Tool loops need a ceiling: a model that keeps calling tools should stop, not bill.
MAX_TOOL_ROUNDS = 6

#: What a panel turn asks for.
#:
#: Short, because the surface brief in the skill already says what a panel is
#: and what it may contain. This only has to name the macro. `Trip()` is bound
#: to `/trip` and `/panel`, so once drawn the panel stays current by data alone:
#: a pressed fare reaches it in one `updateDataModel`, not a further turn.
PANEL_REQUEST = (
    "Draw this surface with `Trip()` — bound, so it stays current by itself. "
    "Only the surface — no prose."
)


#: The model that answers when nobody picks one, and the panel's own model.
#:
#: Flash 3.8 rather than Flash Lite. Lite is faster to a first surface, but on
#: a round trip it reliably priced the outbound hop, said so, and moved on to
#: hotels with the traveller still abroad; Flash 3.8, on the same prompt and
#: tools, recorded the hop home and priced both. A fast wrong answer is not
#: fast. Lite stays one keystroke away in the header.
#:
#: The cost is availability: Flash 3.8 is sometimes busy ("high demand"), which
#: is what `FALLBACK_MODEL` is for.
#:
#: Read from the environment here and nowhere else, so setting `DEFAULT_MODEL`
#: moves every door and every panel together.
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "gemini-3.8-flash")

#: How hard that model thinks when nobody says. See `supported_level`, which
#: clamps this to what the chosen model accepts — Flash 3.8 rejects `minimal`
#: outright, where Flash Lite takes it.
DEFAULT_EFFORT = "low"

#: Who answers when the chosen model is busy. See `_open` in `gemini.py`.
#:
#: A capacity spike on Google's side is not something a traveller halfway
#: through planning can do anything about, and "the model is busy" is a worse
#: answer than a smaller model's surface. So the turn degrades instead of
#: failing, and the client is told which model actually answered.
FALLBACK_MODEL = os.environ.get("FALLBACK_MODEL", "gemini-3.5-flash-lite")


#: Which model draws the panel, and how hard it thinks, for every door.
#:
#: The panel is the record of what somebody decided, so it gets the
#: conversation's model rather than the cheapest one; and it is drawn once per
#: conversation (data keeps it current after that), so the extra seconds are
#: paid once. `PANEL_MODEL` on its own, or `DEFAULT_MODEL` if only that is set.
PANEL_MODEL = os.environ.get("PANEL_MODEL", DEFAULT_MODEL)
PANEL_EFFORT = "low"


def _today(client: Any = None) -> str:
    """Today where the traveller is, not where the container is.

    The server runs in UTC, and a trip is planned in a calendar the traveller is
    holding. At 18:00 in Los Angeles the container has already turned the page:
    "tomorrow" comes back a day late, and "this Saturday" is the wrong Saturday.
    The browser is the only party that knows which day it is for them, so it
    says, and this reads it.

    Read sceptically, because it is untrusted input: a well-formed date within a
    day of the server's own is the only thing that can move this, which covers
    every real timezone and nothing else. A client that sends junk — or a clock
    set to 2019 — gets the server's date, which is what there was before.
    """
    here = _dt.date.today()
    said = client.get("today") if isinstance(client, dict) else None
    if isinstance(said, str):
        try:
            theirs = _dt.date.fromisoformat(said)
        except ValueError:
            return here.isoformat()
        if abs((theirs - here).days) <= 1:
            return theirs.isoformat()
    return here.isoformat()
