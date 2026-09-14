#!/usr/bin/env python3
"""The panel, drawn by each model, scored.

The panel is composed by the agent like everything else here, which means the
only way to know whether it is any good is to draw it and count. This does that.

It exists because a traveller noticed the sidebar looked better on one runtime
than the other, and the first explanation — "the two doors use different
models" — was true and not the reason. Both doors sent byte-identical prompts;
the composition was simply a coin flip, and sometimes the roll came up with no
Change buttons on it. A record of what you decided with no way to correct any of
it looks fine in a screenshot and is inert.

What is scored, per run:

  drew       anything compiled and reached the surface at all
  parts      how many components — a thin panel is a panel missing rows
  change     how many Change buttons, which is the panel's only interaction
  seconds    wall clock

The cause was in `prompts/surface-sidebar.md`: it demonstrated the decisions as
`List(_template(…))`, and a template row is one component that cannot hold a
label and a button side by side. Rows or Change, never both. Fixing the brief
moved flash-3.8 from 1/3 drawn with 0.7 Change to 4/4 with 8.0 — which is the
sort of claim that should be re-runnable rather than remembered.

    GEMINI_API_KEY=... python3 tools/eval/panels.py
    GEMINI_API_KEY=... RUNS=5 python3 tools/eval/panels.py
"""

import asyncio
import os
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "server" / "src"))

from travel_a2ui.brain.express import ExpressStream, Ui  # noqa: E402
from travel_a2ui.brain.skills import build_system_prompt  # noqa: E402
from travel_a2ui.brain.surface import finish  # noqa: E402
from travel_a2ui.doors.interactions import (  # noqa: E402
    CATALOG_ID,
    COMPONENT_NAMES,
    PANEL_REQUEST,
    _CATALOG,
    _parser,
    supported_level,
)
from travel_a2ui.gemini import stream_interaction  # noqa: E402

TODAY = "2027-03-01"

#: A trip with enough decided that the panel has real work to do: a route with
#: two hops, a chosen fare, a chosen stay, and a party that changes on the way
#: back. This is where a thin panel is obviously thin.
TRIP = {
    "origin": "JFK",
    "destination": "Madrid",
    "startDate": "2027-04-12",
    "endDate": "2027-04-19",
    "travelers": 2,
    "selectedFlight": "IB6250",
    "flightPrice": 412,
    "selectedHotel": "Hotel Unico",
    "nightlyPrice": 291,
    "budget": 5000,
    "legs": [
        {
            "origin": "MAD",
            "destination": "JFK",
            "startDate": "2027-04-19",
            "endDate": "2027-04-19",
            "travelers": 3,
        }
    ],
}

CANDIDATES = [
    ("gemini-3.5-flash-lite", "minimal"),  # what the typed door uses today
    ("gemini-3.5-flash-lite", "low"),
    ("gemini-3.8-flash", "low"),  # what the Live door uses
]


async def draw(surface_id: str, model: str, level: str) -> dict:
    system = build_system_prompt(
        variant="express-modular",
        surface=surface_id,
        surface_id=surface_id,
        catalog_id=CATALOG_ID,
        trip=TRIP,
        today=TODAY,
    )
    stream = ExpressStream(
        parser=_parser(surface_id), components=COMPONENT_NAMES, validator=_CATALOG.validator
    )
    began = time.perf_counter()
    events = []
    try:
        async for event in stream_interaction(
            api_key=os.environ["GEMINI_API_KEY"],
            model=model,
            input=[{"type": "user_input", "content": [{"type": "text", "text": PANEL_REQUEST}]}],
            system_instruction=system,
            thinking_level=supported_level(model, level),
        ):
            if event["type"] == "text":
                events.extend(stream.push(event["delta"]))
        events.extend(stream.end())
    except Exception as error:  # noqa: BLE001 - a failure is a result
        return {"drew": False, "error": str(error)[:90], "seconds": time.perf_counter() - began}

    messages = []
    for event in events:
        if isinstance(event, Ui):
            messages.extend(finish(event.messages, TRIP))

    names: list[str] = []
    for message in messages:
        for node in (message.get("updateComponents") or {}).get("components") or []:
            if isinstance(node, dict) and node.get("component"):
                names.append(str(node["component"]))

    return {
        "drew": bool(names),
        "components": len(names),
        "kinds": sorted(set(names)),
        # A panel that is *the record* shows the decisions and offers Change on
        # them. One that is a paragraph does not.
        "changeable": sum(1 for n in names if n in ("Button", "DecisionRow", "PlanRow")),
        "seconds": round(time.perf_counter() - began, 1),
    }


async def main() -> int:
    runs = int(os.environ.get("RUNS", "3"))
    print(f"{'model':26} {'think':8} {'surface':9} {'drew':>5} {'parts':>6} {'change':>7} {'secs':>6}")
    print("-" * 76)
    for model, level in CANDIDATES:
        for surface_id in ("sidebar", "home"):
            rows = [await draw(surface_id, model, level) for _ in range(runs)]
            drew = sum(1 for r in rows if r.get("drew"))
            parts = [r.get("components", 0) for r in rows]
            change = [r.get("changeable", 0) for r in rows]
            secs = [r["seconds"] for r in rows]
            print(
                f"{model:26} {level:8} {surface_id:9} "
                f"{drew}/{runs:<3} {statistics.mean(parts):>6.1f} "
                f"{statistics.mean(change):>7.1f} {statistics.mean(secs):>6.1f}"
            )
            kinds = sorted({k for r in rows for k in r.get("kinds", [])})
            print(f"{'':26} {'':8} {'':9} {', '.join(kinds) or '—'}")
    return 0


sys.exit(asyncio.run(main()))
