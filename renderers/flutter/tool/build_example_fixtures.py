#!/usr/bin/env python3
"""Writes every catalog example as the server sends it, for the Flutter tests.

The examples in `catalogs/a2ui-travel/examples/*.json` are what the model is
shown, so some use this app's macros (`Flights()`, `Trip()`), which no renderer
ever sees. Each one is read here through the server's own pipeline: decompiled
to Express by the SDK, drawn through `Drawing` (the SDK processor, the macros
expanded, every message applied to the renderer mirror), and given the data
the host sends a surface that binds it, for one sample trip. The output is the
list of messages a renderer receives for each example.

    python3 renderers/flutter/tool/build_example_fixtures.py            # write
    python3 renderers/flutter/tool/build_example_fixtures.py --check    # fail if stale
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "server" / "src"))

from a2ui.inference_formats import to_message_models  # noqa: E402

from travel_a2ui.brain import data  # noqa: E402
from travel_a2ui.brain.catalog import processor_for  # noqa: E402
from travel_a2ui.brain.providers.fixture import FixtureProvider  # noqa: E402
from travel_a2ui.brain.tools import ToolContext, run_tool  # noqa: E402
from travel_a2ui.brain.ui import Canvas, Drawing  # noqa: E402

EXAMPLES = ROOT / "catalogs" / "a2ui-travel" / "examples"
OUT = ROOT / "renderers" / "flutter" / "test" / "fixtures" / "examples.json"

#: One trip with a fare chosen, so a panel has something on it.
TRIP = {
    "origin": "JFK",
    "destination": "Madrid",
    "startDate": "2027-04-12",
    "endDate": "2027-04-19",
    "travelers": 2,
    "selectedFlight": "IB6250",
    "flightPrice": 412,
    "airline": "Iberia",
    "flightNumber": "IB6250",
    "departTime": "18:40",
    "arriveTime": "08:15 +1",
}


def _fares() -> list:
    context = ToolContext(trip=dict(TRIP), provider=FixtureProvider(), save=lambda _patch: None, today="2027-03-01")
    args = {"origin": "JFK", "destination": "Madrid", "date": "2027-04-12", "travelers": 2}
    result, _ = asyncio.run(run_tool("search_flights", args, context))
    _, rows = data.lookup_rows("search_flights", result)
    return rows


def _surface_id(messages: list) -> str:
    for message in messages:
        for body in message.values():
            if isinstance(body, dict) and body.get("surfaceId"):
                return str(body["surfaceId"])
    raise ValueError("an example with no surface")


def build() -> str:
    lookups = {"flights": _fares()}
    out = []
    for path in sorted(EXAMPLES.glob("*.json")):
        example = json.loads(path.read_text("utf-8"))
        messages = example["messages"]
        surface_id = _surface_id(messages)

        def values(_surface: str) -> dict:
            return {**data.session_values(TRIP, None), **data.turn_values(lookups, TRIP)}

        drawing = Drawing(Canvas(), surface_id, values, creatable={surface_id})
        # Decompiled by the model's processor, which knows the macros.
        express = processor_for(surface_id).parser.decompile(to_message_models(messages))
        block = f"<a2ui>\n{express}\n</a2ui>"
        events = [*drawing.feed(block), *drawing.close()]
        refused = [event[1] for event in events if event[0] == "rejected"]
        if refused:
            raise SystemExit(f"{path.name}: {refused[0]}")
        wire = [message for event in events if event[0] == "ui" for message in event[2]]
        out.append({"example": path.stem, "surfaceId": surface_id, "messages": wire})
    return json.dumps(out, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = build()
    if args.check:
        if not OUT.exists() or OUT.read_text("utf-8") != text:
            print(
                f"{OUT.relative_to(ROOT)} is stale. Run: python3 {pathlib.Path(__file__).relative_to(ROOT)}",
                file=sys.stderr,
            )
            return 1
        print("Example fixtures are up to date.")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
