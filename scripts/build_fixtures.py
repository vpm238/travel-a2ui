#!/usr/bin/env python3
"""Writes the messages a second renderer is tested against, from the real server.

`renderers/flutter/test/render_test.dart` checks that a flight list the model
drew paints before the lookup returns, and fills in when only the data model
changes. That is only worth anything if the bytes under test are the bytes the
server sends, so they are produced here by the server's own pipeline: the A2UI
processor reads `Flights()`, the macro expands, and the rows are what
`search_flights` returns on the fixture provider, as `updateDataModel`.

    python3 scripts/build_fixtures.py            # write
    python3 scripts/build_fixtures.py --check    # fail if what is on disk is stale
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import warnings

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "server" / "src"))

from travel_a2ui.brain import data  # noqa: E402
from travel_a2ui.brain.providers.fixture import FixtureProvider  # noqa: E402
from travel_a2ui.brain.tools import ToolContext, run_tool  # noqa: E402
from travel_a2ui.brain.ui import Canvas, Drawing  # noqa: E402

OUT = ROOT / "renderers" / "flutter" / "test" / "fixtures" / "flights.json"

TRIP = {"origin": "JFK", "destination": "Madrid", "startDate": "2027-04-12", "travelers": 2}


def build() -> str:
    lookups: dict = {}

    def values(_surface: str) -> dict:
        return {**data.session_values(TRIP, None), **lookups}

    canvas = Canvas()
    drawing = Drawing(canvas, "inline-1", values)
    block = '<a2ui>\nfares = Flights("Finding flights to Madrid")\nroot = Column([fares])\n</a2ui>'
    events = [*drawing.feed(block), *drawing.close()]
    opening = [message for event in events if event[0] == "ui" for message in event[2]]

    context = ToolContext(trip=dict(TRIP), provider=FixtureProvider(), save=lambda _patch: None, today="2027-03-01")
    args = {"origin": "JFK", "destination": "Madrid", "date": "2027-04-12", "travelers": 2}
    result, _ = asyncio.run(run_tool("search_flights", args, context))
    root, rows = data.lookup_rows("search_flights", result)
    lookups[root] = rows
    filled = canvas.provide(values, ["inline-1"])

    return json.dumps({"opening": opening, "filled": filled}, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = build()
    if args.check:
        if not OUT.exists() or OUT.read_text("utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is stale. Run: python3 scripts/build_fixtures.py", file=sys.stderr)
            return 1
        print("Renderer fixtures are up to date.")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
