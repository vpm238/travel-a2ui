#!/usr/bin/env python3
"""Which skill variant actually draws the right thing.

Three variants are generated and checked in — `express-monolithic`,
`express-modular`, `direct-json-monolithic` — and the app has always used the
first because it was first. That is not a reason. This measures them instead:
the same asks through each, scored on things that are true or false rather than
on how the surface felt.

What is scored, per turn:

  drew            a surface compiled and reached the screen at all
  clean           it compiled without the host having to send it back
  controls        every decision is asked for in a control it can be answered
                  in — the `data/controls.json` rule, checked not asked
  expected        the component the scenario is about is actually on the surface
  bound           the surface writes to the trip paths the scenario is about
  rounds          model rounds the turn took
  seconds         wall clock to the last event

Run it:

    GEMINI_API_KEY=... python3 tools/eval/skills.py            # every variant
    GEMINI_API_KEY=... python3 tools/eval/skills.py --runs 3   # more samples
    GEMINI_API_KEY=... python3 tools/eval/skills.py --variant express-modular

Every run costs real tokens against the key in the environment. Four scenarios
times three variants times `--runs`, so the default is twenty-four turns.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import statistics
import sys
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "server" / "src"))

from travel_a2ui.doors.interactions import TurnRequest, run_turn  # noqa: E402
from travel_a2ui.brain.controls import wrong_controls  # noqa: E402
from travel_a2ui.brain.skills import SKILL_VARIANTS  # noqa: E402

#: The asks, and what a right answer to each one contains.
#:
#: Chosen to be the four shapes this app actually draws, not four phrasings of
#: the same one: a form, a list to choose from, a schedule, and a total. A
#: variant can be good at one and poor at another, which is the question behind
#: "one skill or several".
SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "controls",
        "say": "I want to go to Madrid",
        "trip": {},
        # Nothing is settled, so the turn has to ask — and the asking is the
        # thing being scored.
        "expect": {"DateRangePicker", "TravelerCounter", "ChoicePicker"},
        "expect_any": True,
        "paths": {"/trip/startDate", "/trip/origin", "/trip/travelers"},
    },
    {
        "name": "flights",
        "say": "show me the flights",
        "trip": {
            "origin": "JFK",
            "destination": "Madrid",
            "startDate": "2027-04-12",
            "endDate": "2027-04-19",
            "travelers": 2,
        },
        "expect": {"FlightOption"},
        "expect_any": False,
        "paths": set(),
    },
    {
        "name": "itinerary",
        "say": "plan the days",
        "trip": {
            "origin": "JFK",
            "destination": "Madrid",
            "startDate": "2027-04-12",
            "endDate": "2027-04-15",
            "travelers": 2,
            "selectedFlight": "IB6250",
            "flightPrice": 412,
            "selectedHotel": "Hotel Unico",
            "nightlyPrice": 291,
        },
        "expect": {"ItineraryDay", "ActivityItem"},
        "expect_any": False,
        "paths": set(),
    },
    {
        "name": "cost",
        "say": "what does the whole thing come to?",
        "trip": {
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
        },
        "expect": {"PriceSummary"},
        "expect_any": False,
        "paths": set(),
    },
]


def _components(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        update = message.get("updateComponents") or {}
        for node in update.get("components") or []:
            if isinstance(node, dict):
                out.append(node)
    return out


def _paths(messages: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            path = value.get("path")
            if isinstance(path, str):
                found.add(path)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(messages)
    return found


async def one(variant: str, scenario: dict[str, Any], model: str, effort: str) -> dict[str, Any]:
    began = time.perf_counter()
    request = TurnRequest(
        api_key=os.environ["GEMINI_API_KEY"],
        model=model,
        message=scenario["say"],
        trip=dict(scenario["trip"]),
        surface="inline",
        surface_id="inline-1",
        skill=variant,
        effort=effort,
    )

    drawn: list[dict[str, Any]] = []
    retried = False
    failed = False
    rounds = 0
    errors: list[str] = []

    async for event in run_turn(request):
        kind = event["type"]
        if kind == "ui" and event["surfaceId"] == "inline-1":
            drawn.extend(event["messages"])
        elif kind == "ui_error":
            failed = True
        elif kind == "retry":
            retried = True
        elif kind == "usage":
            rounds += 1
        elif kind == "error":
            errors.append(str(event.get("message"))[:90])

    nodes = _components(drawn)
    names = {str(node.get("component")) for node in nodes}
    wanted = scenario["expect"]
    expected = bool(names & wanted) if scenario["expect_any"] else wanted <= names
    complaints = wrong_controls(drawn)

    return {
        "drew": bool(nodes),
        "clean": bool(nodes) and not failed and not retried,
        "controls": not complaints,
        "complaints": complaints,
        "expected": expected,
        "bound": (not scenario["paths"]) or bool(scenario["paths"] & _paths(drawn)),
        "rounds": rounds,
        "seconds": round(time.perf_counter() - began, 1),
        "components": sorted(names),
        "errors": errors,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--variant", action="append")
    parser.add_argument("--scenario", action="append", help="only these, by name")
    parser.add_argument("--model", default=os.environ.get("MODEL", "gemini-3.5-flash-lite"))
    parser.add_argument("--effort", default=os.environ.get("EFFORT", "minimal"))
    parser.add_argument("--json", help="write the raw results here")
    args = parser.parse_args()

    variants = args.variant or list(SKILL_VARIANTS)
    chosen = [s for s in SCENARIOS if not args.scenario or s["name"] in args.scenario]
    results: dict[str, dict[str, list[dict[str, Any]]]] = {}

    for variant in variants:
        results[variant] = {}
        for scenario in chosen:
            rows = []
            for _ in range(args.runs):
                try:
                    rows.append(await one(variant, scenario, args.model, args.effort))
                except Exception as error:  # noqa: BLE001 - a failed turn is a result
                    rows.append({"drew": False, "error": str(error)[:120]})
            results[variant][scenario["name"]] = rows
            marks = "".join("." if row.get("expected") else "x" for row in rows)
            print(f"  {variant:26} {scenario['name']:10} {marks}", flush=True)

    print()
    header = f"{'variant':26} {'scenario':10} {'drew':>5} {'clean':>6} {'ctrls':>6} {'right':>6} {'bound':>6} {'rnds':>5} {'secs':>6}"
    print(header)
    print("-" * len(header))

    def share(rows: list[dict[str, Any]], key: str) -> str:
        hits = sum(1 for row in rows if row.get(key))
        return f"{hits}/{len(rows)}"

    for variant, per in results.items():
        for name, rows in per.items():
            seconds = [row["seconds"] for row in rows if "seconds" in row]
            rounds = [row["rounds"] for row in rows if "rounds" in row]
            print(
                f"{variant:26} {name:10} "
                f"{share(rows, 'drew'):>5} {share(rows, 'clean'):>6} "
                f"{share(rows, 'controls'):>6} {share(rows, 'expected'):>6} "
                f"{share(rows, 'bound'):>6} "
                f"{(statistics.mean(rounds) if rounds else 0):>5.1f} "
                f"{(statistics.mean(seconds) if seconds else 0):>6.1f}"
            )

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(results, indent=2), "utf-8")
        print(f"\nRaw results: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
