#!/usr/bin/env python3
"""A spoken call, driven through the real relay — including a press.

`journey.py` drives the typed door. This drives the other one, which is not the
same agent with a microphone bolted on: a voice call goes through the Live API,
its surfaces are composed by server tools rather than written as Express, and
**a press arrives as a sentence**. The Live API has no equivalent of an A2UI
action to send, so the browser relays the press as the line the transcript
already shows — `select flight — id: "AA3229", price: 281` — and the model has
to turn that back into a `save_trip`. Nothing in the host records it on the way
past, which is the one place this runtime costs something, and the one thing
nobody had ever watched happen.

So this types into a real call and then presses, exactly as `useAgent.ts` does,
and checks the choice landed on the trip.

    # a server with a real key, then:
    GEMINI_API_KEY=… python3 tools/validate/voice.py
    … --base ws://127.0.0.1:8131   somewhere else
    … --quiet                      verdicts only

Text rather than audio deliberately: the relay sends typed turns to the same
session on the same socket (`send_client_content`), so this exercises the whole
path — tools, surfaces, trip, panels — without a microphone or a WAV fixture.
What it does not cover is voice activity detection, which needs real audio.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from typing import Any

try:
    import websockets
except ImportError:  # pragma: no cover - the SDK brings it, but say so clearly
    print("websockets is not installed (it ships with google-genai).", file=sys.stderr)
    raise SystemExit(2)


def press_sentence(name: str, context: dict[str, Any]) -> str:
    """A press, as the browser relays it into a call.

    Mirrors `describeForTranscript` in `apps/web/src/useAgent.ts`. If that
    changes, this has to, because the whole point is to send what a traveller
    actually sends.
    """
    said = ", ".join(
        f"{key}: {json.dumps(value)}"
        for key, value in context.items()
        if value not in (None, "")
    )
    spoken = name.replace("_", " ")
    return f"{spoken} — {said}" if said else spoken


def components(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        for node in (message.get("updateComponents") or {}).get("components") or []:
            if isinstance(node, dict):
                out.append(node)
    return out


def first_press(nodes: list[dict[str, Any]], wanted: str) -> tuple[str, dict[str, Any]] | None:
    """The press on the first card of this kind, with its literal context.

    Only literals: a voice surface is composed by the server from real rows, so
    its cards carry the id and the price as values rather than as bindings.
    """
    for node in nodes:
        if str(node.get("component") or "") != wanted:
            continue
        event = ((node.get("action") or {}).get("event")) or {}
        name = event.get("name")
        if not name:
            continue
        context = {
            key: value
            for key, value in (event.get("context") or {}).items()
            if not isinstance(value, dict)
        }
        return str(name), context
    return None


async def call(base: str, key: str, steps: list[dict[str, Any]], quiet: bool) -> dict[str, Any]:
    session_id = f"validate-{uuid.uuid4().hex[:8]}"
    url = f"{base.rstrip('/')}/api/voice?sessionId={session_id}"
    trip: dict[str, Any] = {}
    drawn: list[dict[str, Any]] = []
    #: Everything currently on screen, newest definition of each id winning —
    #: which is how the renderer merges `updateComponents`.
    on_screen: list[dict[str, Any]] = []
    tools: list[str] = []
    transcript: list[str] = []
    turns: list[dict[str, Any]] = []

    async with websockets.connect(url, max_size=16 * 1024 * 1024) as socket:
        await socket.send(json.dumps({"type": "start", "apiKey": key, "client": {}}))

        async def drain(until: str, limit: float) -> None:
            """Reads frames until the turn ends or the clock runs out."""
            nonlocal trip, drawn
            loop = asyncio.get_running_loop()
            deadline = loop.time() + limit
            while loop.time() < deadline:
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=deadline - loop.time())
                except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                    return
                try:
                    frame = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                kind = frame.get("type")
                if kind == "ui":
                    messages = frame.get("messages") or []
                    drawn.extend(messages)
                    on_screen.extend(messages)
                elif kind == "trip":
                    trip = frame.get("trip") or trip
                elif kind == "tool":
                    tools.append(frame.get("name"))
                    if not quiet:
                        print(f"  tool  {frame.get('name')}("
                              f"{json.dumps(frame.get('input') or {}, ensure_ascii=False)[:180]})")
                elif kind == "transcript" and frame.get("who") == "agent":
                    transcript.append(frame.get("text") or "")
                elif kind == "error":
                    print(f"  ERROR {frame.get('message')}")
                elif kind == until:
                    return

        # The call opens with a `ready` frame before anything is said.
        await drain("ready", 30)

        for number, step in enumerate(steps, 1):
            drawn = []
            tools.clear()
            transcript.clear()

            if "press" in step:
                # What is *on screen*, not what the last turn drew. A surface
                # outlives the turn that drew it — that is the whole point of a
                # card you can come back to — and a turn that only speaks
                # leaves the fares from two turns ago sitting there, pressable.
                # Looking at the last turn alone said "nothing to press" at a
                # screen with four flights on it.
                found = first_press(components(on_screen), step["press"])
                if found is None:
                    if not quiet:
                        print(f"\n-- {number}. press {step['press']}: NOTHING TO PRESS")
                    turns.append({"turn": number, "stopped": f"no {step['press']}"})
                    break
                text = press_sentence(*found)
                if not quiet:
                    print(f"\n-- {number}. [press] {text}")
            else:
                text = step["say"]
                if not quiet:
                    print(f"\n-- {number}. {text!r}")

            await socket.send(json.dumps({"type": "text", "text": text}))
            await drain("turn_end", 120)

            said = " ".join(transcript).strip()
            if not quiet:
                if said:
                    print(f'  says  "{said[:180]}"')
                for node in components(drawn):
                    print(f"  {str(node.get('id', '?')):<12} {node.get('component')}")
                print(f"  trip  {json.dumps(trip, ensure_ascii=False)[:300]}")

            turns.append(
                {
                    "turn": number,
                    "input": text,
                    "tools": list(tools),
                    "components": [str(node.get("component")) for node in components(drawn)],
                    "drawn": list(drawn),
                    "trip": dict(trip),
                }
            )

        await socket.send(json.dumps({"type": "end"}))

    return {"trip": trip, "turns": turns}


SCRIPT = [
    {"say": "JFK to Madrid, the 12th to the 19th of April 2027, two of us"},
    {"say": "show me the flights"},
    {"press": "FlightOption"},
    {"say": "and somewhere to stay"},
    {"press": "HotelCard"},
]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.environ.get("VOICE_BASE", "ws://127.0.0.1:8131"))
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--json")
    args = parser.parse_args()

    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        print("GEMINI_API_KEY is not set.", file=sys.stderr)
        return 2

    run = await call(args.base, key, SCRIPT, args.quiet)
    trip = run["trip"]
    drew = [turn for turn in run["turns"] if turn.get("components")]

    checks = [
        (len(run["turns"]) == len(SCRIPT), "every step in the call was answered"),
        (bool(drew), "the call put something on screen"),
        (
            any("FlightOption" in turn.get("components", []) for turn in run["turns"]),
            "fares were drawn rather than read out",
        ),
        (
            bool(trip.get("startDate") and trip.get("destination")),
            "what was said out loud reached the trip",
        ),
        (
            bool(trip.get("selectedFlight") or any(
                leg.get("selectedFlight") for leg in (trip.get("legs") or [])
            )),
            "the flight that was pressed is recorded",
        ),
        (
            bool(trip.get("selectedHotel") or any(
                leg.get("selectedHotel") for leg in (trip.get("legs") or [])
            )),
            "the stay that was pressed is recorded",
        ),
    ]

    print()
    failed = 0
    for passed, what in checks:
        print(f"  {'ok  ' if passed else 'FAIL'} {what}")
        failed += 0 if passed else 1

    if args.json:
        import pathlib

        pathlib.Path(args.json).write_text(json.dumps(run, indent=2, ensure_ascii=False))

    print(f"\n{failed} failed check(s).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
