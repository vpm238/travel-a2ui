#!/usr/bin/env python3
"""Whole conversations, not single turns.

`skills.py` asks one question and scores the surface that comes back, which is
the right shape for comparing skill variants and the wrong shape for the bug
that actually reached a traveller: the agent priced a flight to Madrid, said
"here are the *outbound* flights", and moved on to hotels. Every turn in that
conversation was individually fine. The *journey* was not.

So this plays a conversation through — the traveler's words, then their presses
— and scores the run rather than the turn:

  reached         every milestone the script names was reached, in order
  stranded        the trip ended somewhere other than home with no way back
  reasked         a question was asked again after it had been answered
  drew            every turn put something on the screen
  turns/seconds   what it cost to get there

A press is answered the way the app answers it: the surface's own commit button,
with the context its bindings resolved to, exactly as `client_to_server.json`
would carry it. Nothing here invents a sentence the traveler did not say.

    GEMINI_API_KEY=... python3 tools/eval/flow.py
    GEMINI_API_KEY=... python3 tools/eval/flow.py --script round-trip --model gemini-3.8-flash
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "server" / "src"))

from travel_a2ui.brain import trip as model# noqa: E402
from travel_a2ui.doors.interactions import (  # noqa: E402
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    SurfaceAction,
    TurnRequest,
    run_turn,
)

#: The conversations worth playing, and what has to be true at the end.
#:
#: Each step is either something the traveler types, or `{"press": …}` — the
#: first button on the last surface, carrying what its bindings resolved to.
SCRIPTS: dict[str, dict[str, Any]] = {
    "round-trip": {
        "say": "I want to go to Madrid for a week in April 2027 from New York, two of us",
        "steps": [
            {"say": "JFK is fine, the 12th to the 19th"},
            {"say": "show me the flights"},
            {"press": "the first fare"},
            {"say": "and somewhere to stay near the middle"},
            {"press": "the first stay"},
            {"say": "plan the days"},
        ],
        # Both hops priced before any stay is offered, and a route that comes
        # back — the failure this whole harness exists for.
        "wants": {"home": True, "hops": 2},
    },
    "multi-city": {
        "say": "SFO to Chicago for two nights then New York for four, then home — "
        "a friend joins me in Chicago so two of us from there",
        "steps": [
            {"say": "leaving April 10th 2027"},
            {"say": "sort out the flights"},
        ],
        "wants": {"home": True, "hops": 3},
    },
    "one-way": {
        "say": "one way from JFK to Madrid on the 12th of April 2027, just me, "
        "I'm staying on after",
        "steps": [{"say": "find me a flight"}],
        # Nothing should nag about a way home on a trip that said it is one-way.
        "wants": {"home": False, "hops": 1},
    },
}


def _components(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        for node in (message.get("updateComponents") or {}).get("components") or []:
            if isinstance(node, dict):
                out.append(node)
    return out


def _first_action(nodes: list[dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    """The surface's own commit button, as A2UI describes it."""
    for node in nodes:
        action = node.get("action")
        event = (action or {}).get("event") if isinstance(action, dict) else None
        if isinstance(event, dict) and event.get("name"):
            context = event.get("context")
            return str(event["name"]), context if isinstance(context, dict) else {}
    return None


def _resolved(context: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """What a renderer would send: bindings resolved against the data model."""
    out: dict[str, Any] = {}
    for key, value in context.items():
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            cursor: Any = data
            for part in value["path"].strip("/").split("/"):
                cursor = cursor.get(part) if isinstance(cursor, dict) else None
            out[key] = cursor
        elif isinstance(value, dict) and "literalString" in value:
            out[key] = value["literalString"]
        else:
            out[key] = value
    return out


async def play(name: str, model_id: str, effort: str, verbose: bool) -> dict[str, Any]:
    script = SCRIPTS[name]
    began = time.perf_counter()

    trip: dict[str, Any] = {}
    resume: str | None = None
    setup: str | None = None
    drawn: list[dict[str, Any]] = []
    asked: list[set[str]] = []
    turns = 0
    blank = 0

    steps = [{"say": script["say"]}, *script["steps"]]
    for step in steps:
        nodes = _components(drawn)
        request_kwargs: dict[str, Any] = {}
        if "press" in step:
            found = _first_action(nodes)
            if found is None:
                # Nothing to press is itself a result: the surface was a dead
                # end, and the conversation cannot continue the way a traveler
                # would have continued it.
                return {
                    "script": name,
                    "stopped": f"nothing to press after turn {turns}",
                    "turns": turns,
                    "seconds": round(time.perf_counter() - began, 1),
                }
            action_name, context = found
            request_kwargs["action"] = SurfaceAction(
                name=action_name,
                surface_id="inline-1",
                context=_resolved(context, {"trip": trip}),
            )
        else:
            request_kwargs["message"] = step["say"]

        request = TurnRequest(
            api_key=os.environ["GEMINI_API_KEY"],
            model=model_id,
            trip=dict(trip),
            surface="inline",
            surface_id="inline-1",
            skill="express-modular",
            effort=effort,
            interaction_id=resume,
            setup=setup,
            **request_kwargs,
        )

        drawn = []
        turns += 1
        async for event in run_turn(request):
            kind = event["type"]
            if kind == "ui" and event["surfaceId"] == "inline-1":
                drawn.extend(event["messages"])
            elif kind == "trip":
                trip = event["trip"]
            elif kind == "__result__":
                # The turn's receipt, as `http.py` takes it: the thread back to
                # Google's copy of the conversation, plus the fingerprint of the
                # prompt half it was started against.
                resume = event["result"].interaction_id or resume
                setup = event["result"].setup or setup
                trip = event["result"].trip or trip

        nodes = _components(drawn)
        if not nodes:
            blank += 1
        # Which trip fields this turn asked for, so a question asked twice is
        # visible as a question asked twice.
        asked.append(
            {
                path.rsplit("/", 1)[-1]
                for node in nodes
                for key in ("value", "start", "end")
                if isinstance(node.get(key), dict)
                for path in [str(node[key].get("path") or "")]
                if path.startswith("/trip/")
            }
        )
        if verbose:
            names = sorted({str(node.get("component")) for node in nodes})
            print(f"    {turns}. {step.get('say') or '[press]':<52} {', '.join(names) or '—'}")

    hops = model.journey(trip)
    home = trip.get("origin")
    comes_home = bool(hops) and hops[-1]["to"] == home
    one_way = "return" in set(trip.get("skip") or [])

    # A question re-asked is one whose answer was already on the trip when it
    # was asked again.
    reasked: set[str] = set()
    answered: set[str] = set()
    for turn_asked in asked:
        reasked |= turn_asked & answered
        answered |= {key for key in turn_asked if trip.get(key) not in (None, "")}

    wants = script["wants"]
    return {
        "script": name,
        "home": comes_home or one_way,
        "wantsHome": wants["home"],
        "hops": len(hops),
        "wantsHops": wants["hops"],
        "stranded": wants["home"] and not comes_home and not one_way,
        "reasked": sorted(reasked),
        "blank": blank,
        "turns": turns,
        "seconds": round(time.perf_counter() - began, 1),
        "trip": trip,
    }


def _home_cell(run: dict[str, Any]) -> str:
    """Whether the journey comes back, judged against what this script wanted."""
    if not run["wantsHome"]:
        return "one-way" if run["home"] else "nagged"
    return "yes" if run["home"] else "STRANDED"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", action="append")
    parser.add_argument("--model", default=os.environ.get("MODEL", DEFAULT_MODEL))
    parser.add_argument("--effort", default=os.environ.get("EFFORT", DEFAULT_EFFORT))
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--json", help="write the raw runs here")
    args = parser.parse_args()

    names = args.script or list(SCRIPTS)
    runs = []
    for name in names:
        print(f"  {name} ({args.model}, {args.effort})", flush=True)
        runs.append(await play(name, args.model, args.effort, not args.quiet))

    print()
    header = (
        f"{'script':12} {'hops':>8} {'home':>9} {'blank':>6} "
        f"{'re-asked':>22} {'turns':>6} {'secs':>6}"
    )
    print(header)
    print("-" * len(header))
    for run in runs:
        if "stopped" in run:
            print(f"{run['script']:12} stopped: {run['stopped']}")
            continue
        print(
            f"{run['script']:12} "
            f"{str(run['hops']) + '/' + str(run['wantsHops']):>8} "
            f"{_home_cell(run):>9} "
            f"{run['blank']:>6} "
            f"{(', '.join(run['reasked']) or '—'):>22} "
            f"{run['turns']:>6} {run['seconds']:>6.1f}"
        )

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(runs, indent=2), "utf-8")
        print(f"\nRaw runs: {args.json}")

    return 0 if all(not run.get("stranded") and not run.get("stopped") for run in runs) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
