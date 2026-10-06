#!/usr/bin/env python3
"""A whole journey, turn by turn, through the real door — and what it drew.

`tools/eval/flow.py` scores a run: milestones reached, questions re-asked,
seconds spent. That is the right shape for comparing models and the wrong shape
for finding out *why* a turn went wrong, because by the time it has a verdict it
has thrown away the surface.

This keeps everything. Per turn it prints the tools called with their
arguments, what the agent said, every component it drew with its bindings, the
trip after, and the route as `journey` reports it. Then it checks the things a
demo depends on: that a press is recorded, that nothing already settled is
asked for again, that the last hop is never told it is missing dates, and that
the journey can actually be finished.

    GEMINI_API_KEY=… python3 tools/validate/journey.py
    … --script stay            one scenario
    … --quiet                  verdicts only
    … --json out.json          the whole recording

It costs real money and it is not in CI. It is what you run before believing
the flow works.

**A press here is a press.** The host draws a skeleton whose rows are bound to
relative paths — `{path: "id"}` resolved against the row being drawn — and the
model's own cards land over it. A traveller presses the card they can see, so
this presses the last matching component and resolves its bindings the way the
renderer does, against the data model the host filled. Pressing the template
instead sends `{"id": null}`, which is a different conversation and the reason
an earlier version of this script reported bugs that were its own.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "server" / "src"))

from travel_a2ui.brain import trip as model  # noqa: E402
from travel_a2ui.doors.interactions import SurfaceAction, TurnRequest, run_turn  # noqa: E402

DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_EFFORT = "low"


# --------------------------------------------------------------------------
# Reading a surface the way a renderer reads one
# --------------------------------------------------------------------------


def components(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        for node in (message.get("updateComponents") or {}).get("components") or []:
            if isinstance(node, dict):
                out.append(node)
    return out


def flatten(node: Any, into: list[tuple[str, Any]], prefix: str = "") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            flatten(value, into, f"{prefix}.{key}" if prefix else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            flatten(value, into, f"{prefix}[{index}]")
    else:
        into.append((prefix, node))


def kind_of(node: dict[str, Any]) -> str:
    return str(node.get("component") or "?")


def resolve(path: str, trip: dict[str, Any], data: dict[str, Any]) -> Any:
    cursor: Any = {"trip": trip, **{key.strip("/"): value for key, value in data.items()}}
    for part in path.strip("/").split("/"):
        if isinstance(cursor, list) and part.isdigit():
            cursor = cursor[int(part)] if int(part) < len(cursor) else None
        else:
            cursor = cursor.get(part) if isinstance(cursor, dict) else None
    return cursor


def pressable(
    nodes: list[dict[str, Any]], wanted: str, trip: dict[str, Any], data: dict[str, Any]
) -> tuple[str, dict[str, Any]] | None:
    """The press a traveller would make on the newest card of this kind."""
    for node in reversed(nodes):
        if wanted != "*" and kind_of(node) != wanted:
            continue
        flat: list[tuple[str, Any]] = []
        flatten(node, flat)
        name = next((value for path, value in flat if path.endswith("event.name")), None)
        if not name:
            continue

        raw: dict[str, Any] = {}
        for path, value in flat:
            marker = "event.context."
            at = path.find(marker)
            if at >= 0:
                raw[path[at + len(marker) :]] = value

        context: dict[str, Any] = {}
        for key, value in raw.items():
            field = key.split(".")
            if field[-1] == "path" and isinstance(value, str):
                if value.startswith("/"):
                    context[field[0]] = resolve(value, trip, data)
                else:
                    # A row template's binding, resolved against the rows the
                    # host filled — which is the card the traveller sees.
                    rows = next(
                        (
                            found
                            for _, found in reversed(list(data.items()))
                            if isinstance(found, list) and found and isinstance(found[0], dict)
                        ),
                        [],
                    )
                    context[field[0]] = rows[0].get(value) if rows else None
            elif field[-1] in ("literalString", "literalNumber", "literalBoolean"):
                context[field[0]] = value
            else:
                context[key] = value
        return str(name), context
    return None


# --------------------------------------------------------------------------
# The journeys
# --------------------------------------------------------------------------

SCRIPTS: dict[str, dict[str, Any]] = {
    "stay": {
        "why": "One city, both hops ticketed, a stay chosen, and a total off real fares.",
        "steps": [
            {"say": "JFK to Madrid, 12th to the 19th of April 2027, two of us"},
            {"say": "show me the flights"},
            {"press": "FlightOption"},
            {"press": "FlightOption"},
            {"say": "and somewhere to stay"},
            {"press": "HotelCard"},
            {"say": "what does it come to?"},
        ],
        "wants": {"tickets": 2, "stay": True},
    },
    "whole trip": {
        "why": "The demo path: flights, a stay, the days, the total, and a plan to share.",
        "steps": [
            {"say": "JFK to Madrid, 12th to the 19th of April 2027, two of us"},
            {"press": "FlightOption"},
            {"press": "FlightOption"},
            {"say": "find us somewhere to stay"},
            {"press": "HotelCard"},
            {"say": "plan the days"},
            {"say": "what does the whole thing cost?"},
            {"say": "share it with my partner"},
        ],
        "wants": {"tickets": 2, "stay": True, "days": True, "shared": True},
    },
    "multi-city": {
        "why": "Three hops, three parties, three dates — and a counter for every hop.",
        "steps": [
            {
                "say": "SFO to Chicago for two nights then New York for four, then home — "
                "a friend joins me in Chicago so two of us from there"
            },
            {"say": "leaving April 10th 2027"},
            {"say": "sort out the flights"},
        ],
        "wants": {"hops": 3, "counters": 3},
    },
    "berlin": {
        "why": "The demo prompt: two out, one back, a hotel by the Kurfürstendamm.",
        "steps": [
            {"say": "A trip for two from Copenhagen to Berlin, leaving next monday, "
                    "coming back next thursday, but only one person on the way back. "
                    "Include hotel close to Kurfürstendamm."},
            {"press": "FlightOption"},
            {"press": "FlightOption"},
            {"press": "HotelCard"},
            {"say": "what does it come to?"},
        ],
        "wants": {"tickets": 2, "stay": True},
    },
    "one-way": {
        "why": "A journey that does not come back is not missing a hop.",
        "steps": [
            {
                "say": "one way from JFK to Madrid on the 12th of April 2027, just me, "
                "I'm staying on after"
            },
            {"say": "find me a flight"},
        ],
        "wants": {"oneWay": True},
    },
}


async def play(name: str, model_id: str, effort: str, quiet: bool) -> dict[str, Any]:
    script = SCRIPTS[name]
    trip: dict[str, Any] = {}
    resume: str | None = None
    setup: str | None = None
    drawn: list[dict[str, Any]] = []
    data: dict[str, Any] = {}
    record: list[dict[str, Any]] = []
    counters: list[str] = []
    asked: list[list[str]] = []

    if not quiet:
        print(f"\n{'=' * 78}\n{name} — {script['why']}\n{'=' * 78}")

    for number, step in enumerate(script["steps"], 1):
        kwargs: dict[str, Any] = {}
        if "press" in step:
            found = pressable(components(drawn), step["press"], trip, data)
            if found is None:
                if not quiet:
                    print(f"\n-- {number}. press {step['press']}: NOTHING TO PRESS")
                record.append({"turn": number, "stopped": f"no {step['press']} to press"})
                break
            action_name, context = found
            if not quiet:
                print(f"\n-- {number}. [press {action_name} {json.dumps(context, ensure_ascii=False)}]")
            kwargs["action"] = SurfaceAction(
                name=action_name, surface_id="inline-1", context=context
            )
        else:
            if not quiet:
                print(f"\n-- {number}. {step['say']!r}")
            kwargs["message"] = step["say"]

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
            **kwargs,
        )

        drawn = []
        said: list[str] = []
        tools: list[dict[str, Any]] = []
        retries: list[str] = []
        async for event in run_turn(request):
            kind = event["type"]
            if kind == "text":
                said.append(event["delta"])
            elif kind == "tool":
                tools.append({"name": event["name"], "input": event["input"]})
            elif kind == "retry":
                retries.append(event["reason"])
            elif kind in ("error", "ui_error"):
                retries.append(str(event.get("message")))
            elif kind == "ui" and event["surfaceId"] == "inline-1":
                drawn.extend(event["messages"])
                for message in event["messages"]:
                    update = message.get("updateDataModel")
                    if isinstance(update, dict) and isinstance(update.get("path"), str):
                        data[update["path"]] = update.get("value")
                    created = (message.get("createSurface") or {}).get("dataModel")
                    if isinstance(created, dict):
                        for key, value in created.items():
                            data[f"/{key}"] = value
            elif kind == "trip":
                trip = event["trip"]
            elif kind == "__result__":
                resume = event["result"].interaction_id or resume
                setup = event["result"].setup or setup
                trip = event["result"].trip or trip

        nodes = components(drawn)
        # Which hops' parties this surface asked about, and which trip fields —
        # so a question asked twice is visible as a question asked twice.
        bound: set[str] = set()
        for node in nodes:
            flat: list[tuple[str, Any]] = []
            flatten(node, flat)
            for path, value in flat:
                if path.endswith((".value.path", ".start.path", ".end.path")) or path in (
                    "value.path",
                    "start.path",
                    "end.path",
                ):
                    if isinstance(value, str) and value.startswith("/trip/"):
                        bound.add(value)
                        if value.endswith("travelers"):
                            counters.append(value)
        asked.append(sorted({path.rsplit("/", 1)[-1] for path in bound}))

        if not quiet:
            for call in tools:
                print(f"  tool  {call['name']}({json.dumps(call['input'], ensure_ascii=False)[:220]})")
            for reason in retries:
                print(f"  RETRY {reason[:160]}")
            spoken = "".join(said).strip().replace("\n", " ")
            if spoken:
                print(f'  says  "{spoken[:180]}"')
            for node in nodes:
                body = {key: value for key, value in node.items() if key != "id"}
                print(f"  {str(node.get('id', '?')):<14} {kind_of(node):<16} "
                      f"{json.dumps(body, ensure_ascii=False)[:150]}")
            print(f"  trip  {json.dumps(trip, ensure_ascii=False)[:400]}")

        record.append(
            {
                "turn": number,
                "input": step.get("say") or f"[press {step.get('press')}]",
                "tools": [call["name"] for call in tools],
                "retries": retries,
                "components": [kind_of(node) for node in nodes],
                "bound": sorted(bound),
                "trip": trip,
            }
        )

    return {"script": name, "trip": trip, "turns": record, "counters": counters, "asked": asked}


# --------------------------------------------------------------------------
# What a demo depends on
# --------------------------------------------------------------------------


def verdicts(run: dict[str, Any]) -> list[tuple[bool, str]]:
    trip = run["trip"]
    wants = SCRIPTS[run["script"]]["wants"]
    hops = model.journey(trip)
    out: list[tuple[bool, str]] = []

    def check(passed: bool, what: str) -> None:
        out.append((bool(passed), what))

    # Nothing in the route is ever told it is missing dates it cannot have.
    check(
        not any("dates" in hop["wants"] and hop.get("startDate") for hop in hops),
        "no hop is asked for dates it already gave",
    )
    # And no turn ever drew a date control once the dates were settled.
    settled = False
    redrawn = False
    for turn in run["turns"]:
        if settled and any(path.endswith(("startDate", "endDate")) for path in turn["bound"]):
            redrawn = True
        if turn["trip"].get("startDate"):
            settled = True
    check(not redrawn, "the dates are not asked for again once given")
    check(
        not any(turn["retries"] for turn in run["turns"]),
        "no turn had to be redrawn or repaired",
    )
    check(
        all(turn.get("components") or turn.get("tools") for turn in run["turns"]),
        "every turn did something",
    )

    if "tickets" in wants:
        chosen = sum(1 for hop in hops if hop.get("selectedFlight"))
        check(chosen >= wants["tickets"], f"{wants['tickets']} hop(s) ticketed — got {chosen}")
    if wants.get("stay"):
        check(
            any(hop.get("selectedHotel") for hop in hops),
            "the stay that was pressed is recorded",
        )
    if wants.get("days"):
        check(bool(trip.get("days")), "the days are recorded, not just drawn")
    if wants.get("shared"):
        check(
            any("share_plan" in turn["tools"] for turn in run["turns"]),
            "the plan can be shared",
        )
    if "hops" in wants:
        check(len(hops) == wants["hops"], f"{wants['hops']} hops — got {len(hops)}")
    if "counters" in wants:
        distinct = len(set(run["counters"]))
        check(
            distinct >= wants["counters"],
            f"a party counter for each of {wants['counters']} hops — got {distinct}",
        )
    if wants.get("oneWay"):
        check(trip.get("oneWay") is True, "the trip records that it does not come back")

    return out


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", action="append")
    parser.add_argument("--model", default=os.environ.get("MODEL", DEFAULT_MODEL))
    parser.add_argument("--effort", default=os.environ.get("EFFORT", DEFAULT_EFFORT))
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--json", help="write the whole recording here")
    args = parser.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set.", file=sys.stderr)
        return 2

    runs = []
    for name in args.script or list(SCRIPTS):
        runs.append(await play(name, args.model, args.effort, args.quiet))

    print(f"\n{'=' * 78}")
    failed = 0
    for run in runs:
        print(f"\n{run['script']}")
        for passed, what in verdicts(run):
            print(f"  {'ok  ' if passed else 'FAIL'} {what}")
            failed += 0 if passed else 1

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(runs, indent=2, ensure_ascii=False))
        print(f"\nRecording: {args.json}")

    print(f"\n{failed} failed check(s).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
