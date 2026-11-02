"""The host's pre-draw, captured so a second renderer can be tested against it.

`renderers/flutter/test/render_test.dart` asserts that the Flutter client paints
a lookup's layout before any data arrives, and fills it in when only the data
model changes. That is the claim the whole second-renderer exercise is about —
and it is only worth anything if the bytes under test are the bytes the server
actually sends, rather than a hand-written approximation that agrees with
whatever the test already believes.

So this writes them. `opening_express` is what the host draws the moment a
lookup is dispatched, `seed_rows` is the blank rows that give it something to
shimmer, and both go through `finish` exactly as the door sends them.

    python3 tools/parity/skeleton.py            # write it
    python3 tools/parity/skeleton.py --check     # fail if it is stale

The test was referencing this file before anything produced it, which is how it
came to expect four blank rows where `SEEDED_ROWS` is three: a golden nobody
regenerates cannot disagree with the code, because it is not there to disagree.
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "server" / "src"))

from travel_a2ui.brain.catalog import PROTOCOL_VERSION, parser_for  # noqa: E402
from travel_a2ui.brain.express import as_wire  # noqa: E402
from travel_a2ui.brain.finishing import finish  # noqa: E402
from travel_a2ui.brain.macros import (  # noqa: E402
    expand,
    landing_for,
    opening_express,
    seed_rows,
)

OUT = ROOT / "tools" / "parity" / "__golden__" / "skeleton.json"

#: The trip the skeleton is drawn against, and what each lookup is asked for.
#:
#: Settled, because a pre-draw only happens once a lookup can run — and the
#: heading is the agent's, passed in `draw:`, so it is fixed here rather than
#: invented by the renderer.
TRIP = {
    "origin": "JFK",
    "destination": "Madrid",
    "startDate": "2027-04-12",
    "endDate": "2027-04-19",
    "travelers": 2,
}

CASES: dict[str, dict[str, str]] = {
    "search_flights": {"heading": "Finding flights", "selected": "/trip/selectedFlight"},
    "search_hotels": {"heading": "Finding places to stay", "selected": "/trip/selectedHotel"},
}

#: One row of real data per lookup, so a test can prove the rows fill in when
#: *only* the data model changes — no components, no redraw.
FILLED: dict[str, list[dict[str, object]]] = {
    "search_flights": [
        {
            "id": "IB6250",
            "airline": "Iberia",
            "flightNumber": "IB6250",
            "origin": "JFK",
            "destination": "MAD",
            "departTime": "18:40",
            "arriveTime": "08:15",
            "duration": "7h 35m",
            "stops": "Nonstop",
            "price": "$412",
            "priceValue": 412,
        }
    ],
    "search_hotels": [
        {
            "id": "h_MAD_1",
            "name": "Hotel Villa Real",
            "neighborhood": "Retiro",
            "rating": "4.6 (812)",
            "price": "$210 / night",
            "priceValue": 210,
        }
    ],
}


def captured() -> dict[str, object]:
    out: dict[str, object] = {}
    for tool, draw in CASES.items():
        source = opening_express(tool, draw, "inline-1")
        drawn = finish(
            as_wire(expand(parser_for("inline-1").compile(source, is_final=True), TRIP)),
            TRIP,
        )
        out[tool] = {
            "express": source,
            # The order the door yields them in: the card, then the blank rows.
            "opening": [*drawn, *seed_rows(tool, "inline-1", PROTOCOL_VERSION)],
            "path": landing_for(tool),
            "filled": [
                {
                    "version": PROTOCOL_VERSION,
                    "updateDataModel": {
                        "surfaceId": "inline-1",
                        "path": landing_for(tool),
                        "value": FILLED[tool],
                    },
                }
            ],
        }
    return out


def main() -> int:
    captured_now = json.dumps(captured(), indent=2, ensure_ascii=False) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists():
            print(f"{OUT} is missing. Run: python3 tools/parity/skeleton.py", file=sys.stderr)
            return 1
        if OUT.read_text("utf-8") != captured_now:
            print(
                f"{OUT} is stale — the host draws something else now.\n"
                "Run: python3 tools/parity/skeleton.py",
                file=sys.stderr,
            )
            return 1
        print(f"{OUT.name} matches what the host draws.")
        return 0
    OUT.write_text(captured_now, "utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} for {', '.join(CASES)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
