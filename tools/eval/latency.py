#!/usr/bin/env python3
"""Why the first interface takes so long, and whether warming it up helps.

The app's own timing disclosure says things like "Interface in 18.9 s" on a
first turn and a few seconds on every turn after, which is the complaint this
measures: not that the agent is slow, but that it is slow exactly once, at the
moment somebody is deciding whether this thing works.

The suspicion is the system instruction. It is about fifteen thousand tokens —
the role, the flow, the journey, the inventory, the controls and the generated
skill — and the Interactions API is *stateful*, so it is sent once when a
conversation starts and never again:

    turn 1, system_instruction sent              5,411 input tokens
    turn 2, previous_interaction_id, no system      44 input tokens

If that is where the time goes, then a conversation that has already said
something cheap is a conversation whose first *real* turn is fast — and the app
could do that on page load, before anybody types.

Three conditions, same ask, same model:

    cold     a new conversation; the ask is the first thing it sees
    second   the same conversation's second turn, for the floor
    warmed   a throwaway turn first, then the ask as turn two

If `warmed` looks like `second`, a warm-up on page load is worth having and the
fix is a few lines. If it looks like `cold`, the prompt is not the problem and
this says so before anybody builds the button.

    GEMINI_API_KEY=... python3 tools/eval/latency.py
    GEMINI_API_KEY=... RUNS=3 python3 tools/eval/latency.py
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "server" / "src"))

from travel_a2ui.doors.interactions import (  # noqa: E402
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    TurnRequest,
    run_turn,
)

ASK = "Six days in Madrid in April 2027, two of us, flying from JFK. Show me flights."
#: Cheap, and not a question — it should not send the agent looking anything up.
WARMUP = "hello"


async def turn(message: str, resume: dict | None) -> dict:
    """One turn, and the marks the server already keeps for it."""
    request = TurnRequest(
        api_key=os.environ["GEMINI_API_KEY"],
        model=DEFAULT_MODEL,
        effort=DEFAULT_EFFORT,
        message=message,
        trip=dict((resume or {}).get("trip") or {}),
        surface="inline",
        surface_id="inline-1",
        skill="express-modular",
        interaction_id=(resume or {}).get("interaction_id"),
        setup=(resume or {}).get("setup"),
    )
    marks: dict[str, float] = {}
    out: dict = {"resume": dict(resume or {})}
    async for event in run_turn(request):
        if event["type"] == "timing":
            marks = event["ms"]
        elif event["type"] == "__result__":
            result = event["result"]
            out["resume"] = {
                "interaction_id": result.interaction_id,
                "setup": result.setup,
                "trip": result.trip,
            }
    out["marks"] = marks
    return out


async def main() -> int:
    runs = int(os.environ.get("RUNS", "2"))
    rows: dict[str, list[dict[str, float]]] = {"cold": [], "second": [], "warmed": []}

    for index in range(runs):
        print(f"  run {index + 1}/{runs}", flush=True)

        # cold, then the same conversation again for the floor
        first = await turn(ASK, None)
        rows["cold"].append(first["marks"])
        second = await turn("and somewhere to stay near the middle", first["resume"])
        rows["second"].append(second["marks"])

        # warmed: a throwaway turn, then the real ask
        warm = await turn(WARMUP, None)
        real = await turn(ASK, warm["resume"])
        rows["warmed"].append(real["marks"])
        rows.setdefault("the warm-up itself", []).append(warm["marks"])

    def mean(marks: list[dict[str, float]], key: str) -> float:
        values = [m[key] for m in marks if key in m]
        return statistics.mean(values) / 1000 if values else float("nan")

    print()
    header = f"{'condition':20} {'firstWord':>10} {'firstSurface':>13} {'answered':>10} {'done':>8}"
    print(header)
    print("-" * len(header))
    for name, marks in rows.items():
        print(
            f"{name:20} {mean(marks, 'firstWord'):>10.1f} {mean(marks, 'firstSurface'):>13.1f} "
            f"{mean(marks, 'answered'):>10.1f} {mean(marks, 'done'):>8.1f}"
        )
    print("\n(seconds; nan means the turn never reached that mark)")
    return 0


sys.exit(asyncio.run(main()))
