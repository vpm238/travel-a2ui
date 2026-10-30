"""The choices a door makes before the agent is asked anything.

Which model answers, how hard it thinks, who answers when it is busy, which
model draws the panels, and what a panel redraw asks for. None of it is about a
particular door, and all of it has to be the same in every door — a traveller
who switches from typing to talking should not get a different agent.

They were in `interactions.py`, and the voice relay reached across for them with
imports written inside its function bodies. Door importing door is how the two
quietly end up on two models, which is exactly what happened once: the typed
door drew panels with Flash Lite at `minimal` and the Live door drew them with
Flash 3.8 at `low`, off byte-identical prompts.

`_today` is here for the same reason: both doors are told what day it is by the
client, and both have to read that the same sceptical way.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

#: Tool loops need a ceiling: a model that keeps calling tools should stop, not bill.
MAX_TOOL_ROUNDS = 6

#: What a panel redraw asks for.
#:
#: Short, because the surface brief in the skill already says what a panel is
#: and what it may contain. This only has to name the macro.
#:
#: Naming it is the whole point. The old wording — "redraw this surface for
#: where the trip stands now" — got a panel written out by hand, every value a
#: literal read off the trip it was handed. A panel like that is right once and
#: then frozen: the host files a pressed fare at `/trip/selectedFlight` the
#: instant it lands, before the model is even asked, and the literal on screen
#: cannot hear it. So the traveller pressed a fare and watched the sidebar say
#: nothing about it until a whole further turn had drawn a whole further panel —
#: measured at 20.8s and 29.0s, which is this turn plus the one after it.
#:
#: `Trip()` is bound, so the same press moves it in the time a websocket frame
#: takes, and this request is then needed once per route rather than once per
#: decision.
PANEL_REQUEST = (
    "Draw this surface with `Trip()` — bound, so it stays current by itself. "
    "Only the surface — no prose."
)


#: The model that answers when nobody picks one, and the panel's own model.
#:
#: This was Flash Lite, picked on latency: fastest to a first surface, and for a
#: turn that is mostly recall — the catalog is in the prompt, the job is to bind
#: three components — that looked like the right trade.
#:
#: It was the wrong trade, and the thing that showed it was the way home. A
#: round trip needs a ticket each way; the skills say so, the route facts say
#: the journey does not come back, and the `search_flights` result says it again
#: at the moment the fares arrive. Flash Lite read all three, answered "here are
#: the *outbound* flights" — so it had understood — and moved on to hotels, with
#: the traveller still in Madrid. Four attempts, at `minimal` and at `low`, all
#: four the same. On Flash 3.8, the same prompt and the same tools, first try:
#: it recorded the hop home as a leg, priced both hops, and had an opinion about
#: each.
#:
#: So the ceiling was never the instructions. A demo that is fast at being wrong
#: is not fast, and the seconds are worth an agent that finishes the journey.
#: Flash Lite is still one keystroke away in the header for anyone who wants to
#: watch the difference.
#:
#: The honest caveat, measured on the same eval, is availability. Of twelve
#: turns on Flash 3.8, four came back with no surface at all — every one of them
#: "currently experiencing high demand", a capacity spike rather than anything
#: the model got wrong. Of the eight that ran, eight drew the right thing; Flash
#: Lite, never once busy, drew it ten times in twelve. That is what
#: `FALLBACK_MODEL` is for: the turn degrades to the model that is up rather
#: than ending the conversation, and the traveller is told it happened.
#:
#: Lives here rather than in `main.py` because the voice relay redraws the
#: standing panel with its own model call, and a second opinion about the
#: default is how two doors quietly end up on two models.
DEFAULT_MODEL = "gemini-3.8-flash"

#: How hard that model thinks when nobody says. See `supported_level`, which
#: clamps this to what the chosen model accepts — Flash 3.8 rejects `minimal`
#: outright, where Flash Lite takes it.
DEFAULT_EFFORT = "low"

#: Who answers when the chosen model is busy. See `_open` in `gemini.py`.
#:
#: Measured on the eval that settled the default: twelve of thirty-six turns on
#: Flash 3.8 came back with no surface at all, every one of them "currently
#: experiencing high demand" — the model was not there, rather than wrong. A
#: capacity spike on Google's side is not something a traveller halfway through
#: planning a trip can do anything about, and "the model is busy" is a worse
#: answer than a smaller model's surface. So the turn degrades instead of dying,
#: and the client is told which model actually answered.
FALLBACK_MODEL = "gemini-3.5-flash-lite"


#: Which model draws the panels, and how hard it thinks — for **every** door.
#:
#: Named once because it used to be named twice, differently: the typed door
#: drew panels with Flash Lite at `minimal` and the Live door drew them with
#: Flash 3.8 at `low`, off byte-identical prompts. Same brain, same brief, two
#: different answers, and a traveller who switched runtimes saw the sidebar
#: change character for no reason they could act on.
#:
#: Chosen on numbers. `tools/eval/panels.py`, one fixed trip with two hops and
#: two party sizes, two passes of four and five runs, after the sidebar brief
#: stopped asking for Change buttons inside a template:
#:
#:     flash-lite/minimal   3/4 then 5/5 drew   ·  5.8 then 12.4 Change  ·  ~3.1s
#:     flash-3.8/low        4/4 then 5/5 drew   ·  8.0 then  9.6 Change  ·  ~5.6s
#:
#: Both are good now, which is the actual finding: the bug was the brief, not
#: the model — before the fix this cell was 0.0 to 3.3 Change buttons on a
#: sidebar whose only interaction is Change. Flash 3.8 is 9/9 across the two
#: passes against 8/9, and the panel is the record of what somebody decided, so
#: the two and a half seconds buys the run that does not come back thin. Worth
#: re-running when either model moves; the small one may well win it back.
PANEL_MODEL = DEFAULT_MODEL
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
