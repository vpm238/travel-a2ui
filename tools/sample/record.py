#!/usr/bin/env python3
"""Records the sample trip a first visit opens on.

A first visit used to open on a heading, three suggestions and — with no key —
a full-screen form. Nothing on the page showed what the agent *does*, which is
the one thing a visitor came to find out, and finding out cost a key.

The sample is a real conversation with this agent, recorded through the same
door a browser uses and replayed by the browser through the same handler as a
live turn. Nothing in it was composed by the host or written by hand: every
card is one the agent drew, every row is one the host's lookup filled, and the
panel is the one the agent composed. That is the point of recording it rather
than building it — the app's interface is agent-driven, and a sample laid out
by the host would demonstrate something this app does not do.

    # a server with a real key on it, then:
    python3 tools/sample/record.py --base http://127.0.0.1:8080

It costs real money and is not in CI. `apps/server/tests/test_sample_trip.py`
is: it validates every recorded A2UI message against the current catalog, so a
catalog change that would make the sample wrong fails a test, and this is what
you run to fix it.

What is kept is what a browser keeps. What is dropped is what belongs to the
recording rather than the conversation: the session id, token usage, timings,
and the interaction id — a pointer into the recorder's own Gemini account,
which nobody replaying this could follow. The trip and its shape stay, because
that is how the next live turn picks up from the sample (`_resumed` in
`doors/http.py`), exactly as it would from any turn a browser had seen.

The key is read from the server's environment, never from here, and nothing
this writes contains it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import uuid
from typing import Any

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "validate"))
sys.path.insert(0, str(ROOT / "apps" / "server" / "src"))

from journey import components, kind_of  # noqa: E402

OUT = ROOT / "apps" / "web" / "public" / "sample-trip.json"

#: The standing surfaces, which a live turn should replace rather than sit
#: beside. Every other surface is renamed — see `_rename`.
STANDING = {"sidebar", "home"}

#: One city, both hops ticketed, a stay chosen: enough that the panel has every
#: row it can have, short enough to read in a glance.
STEPS: list[dict[str, str]] = [
    {"say": "JFK to Madrid, 12th to the 19th of April 2027, two of us"},
    {"press": "FlightOption"},
    {"press": "FlightOption"},
    {"say": "and somewhere to stay near Sol"},
    {"press": "HotelCard"},
]

#: What a browser keeps. Everything else is about the recording.
#: Not `served_by`: which model stood in for a busy one is a fact about the
#: recording session, and a sample has no model the visitor picked.
KEPT = {"text", "ui", "tool", "tool_result", "trip", "resume", "done"}


def _rename(surface_id: str) -> str:
    """Moves an inline card out of the way of the live conversation's ids.

    A live turn after the sample starts a new server session, which numbers its
    cards from `inline-1` again — and a card with the same id would land on the
    sample's first card and redraw it.
    """
    return surface_id if surface_id in STANDING or surface_id.startswith("sample-") else f"sample-{surface_id}"


def _renamed(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _rename(item) if key == "surfaceId" and isinstance(item, str) else _renamed(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_renamed(item) for item in value]
    return value


def _events(response: httpx.Response) -> list[dict[str, Any]]:
    events = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def _resolve(binding: Any, row: dict[str, Any], data: dict[str, Any]) -> Any:
    """A context value as a renderer resolves it for the first row of a list."""
    if not isinstance(binding, dict):
        return binding
    path = binding.get("@path", binding.get("path"))
    if not isinstance(path, str):
        return binding
    if not path.startswith("/"):
        return row.get(path)
    head, _, rest = path[1:].partition("/")
    cursor: Any = data.get(f"/{head}")
    for part in [p for p in rest.split("/") if p]:
        if isinstance(cursor, list) and part.isdigit():
            cursor = cursor[int(part)] if int(part) < len(cursor) else None
        else:
            cursor = cursor.get(part) if isinstance(cursor, dict) else None
    return cursor


def _said(message: Any, row: dict[str, Any], data: dict[str, Any]) -> str | None:
    """An `event.userMessage` as a renderer resolves it: `formatString` over the row."""
    if isinstance(message, str):
        return message or None
    if not (isinstance(message, dict) and message.get("@call") == "formatString"):
        return None
    template = str((message.get("args") or {}).get("value") or "")

    def value(match: re.Match[str]) -> str:
        found = _resolve({"@path": match.group(1)}, row, data)
        return "" if found is None else str(found)

    said = re.sub(r"\$\{([^}]+)\}", value, template)
    return re.sub(r"\s+", " ", said).replace(" ,", ",").strip() or None


def _press(
    drawn: list[tuple[str, dict[str, Any]]], wanted: str, trip: dict[str, Any], data: dict[str, Any]
) -> dict[str, Any] | None:
    """The press a traveller would make on the first card of the newest list of this kind.

    Resolved the way a renderer resolves it: a card in a list is a template, and
    its relative bindings read the row the `List` it belongs to is bound to —
    found from the list itself, not guessed from whichever rows arrived last.
    """
    del trip  # the data model already carries /trip
    nodes = [(sid, node) for sid, message in drawn for node in components([message])]
    lists = {
        node["children"]["componentId"]: node["children"].get("path")
        for _, node in nodes
        if isinstance(node.get("children"), dict) and "componentId" in node["children"]
    }
    for surface_id, node in reversed(nodes):
        if kind_of(node) != wanted:
            continue
        event = (node.get("action") or {}).get("event") or {}
        if not event.get("name"):
            continue
        rows = data.get(lists.get(node.get("id"), ""), [])
        row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
        context = {key: _resolve(value, row, data) for key, value in (event.get("context") or {}).items()}
        if not any(value not in (None, "") for value in context.values()):
            continue  # a placeholder card, before its rows arrived
        pressed = {
            "name": event["name"],
            "surfaceId": surface_id,
            "sourceComponentId": str(node.get("id")),
            "context": context,
        }
        said = _said(event.get("userMessage"), row, data)
        if said:
            pressed["userMessage"] = said
        return pressed
    return None


def record(base: str) -> dict[str, Any]:
    session = f"sample-{uuid.uuid4().hex[:8]}"
    resume: dict[str, Any] | None = None
    trip: dict[str, Any] = {}
    data: dict[str, Any] = {}
    drawn: list[tuple[str, dict[str, Any]]] = []
    turns: list[dict[str, Any]] = []
    served: str | None = None

    with httpx.Client(base_url=base, timeout=180) as client:
        meta = client.get("/api/meta").json()
        if not meta.get("keyProvided"):
            raise SystemExit("The server has no key. Start it with GEMINI_API_KEY set.")

        for number, step in enumerate(STEPS, 1):
            body: dict[str, Any] = {"sessionId": session, "surface": "inline"}
            if resume:
                body["resume"] = resume
            if "press" in step:
                action = _press(drawn, step["press"], trip, data)
                if action is None:
                    raise SystemExit(f"step {number}: no {step['press']} on screen to press")
                body["action"] = action
                turn: dict[str, Any] = {"action": _renamed(action)}
            else:
                body["message"] = step["say"]
                turn = {"message": step["say"]}
            print(f"-- {number}. {step}", file=sys.stderr)

            with client.stream("POST", "/api/chat", json=body) as response:
                response.raise_for_status()
                events = _events(response)

            errors = [event for event in events if event.get("type") == "error"]
            if errors:
                raise SystemExit(f"step {number} failed: {errors[0].get('message')}")

            kept: list[dict[str, Any]] = []
            for event in events:
                kind = event.get("type")
                if kind == "resume":
                    resume = {key: event[key] for key in ("interactionId", "trip", "shape", "setup") if event.get(key)}
                    event = {key: value for key, value in event.items() if key in ("type", "trip", "shape")}
                if kind == "trip" and isinstance(event.get("trip"), dict):
                    trip = event["trip"]
                if kind == "served_by":
                    served = event.get("model")
                if kind == "ui":
                    for message in event.get("messages", []):
                        drawn.append((event["surfaceId"], message))
                        update = message.get("updateDataModel")
                        if isinstance(update, dict) and isinstance(update.get("path"), str):
                            data[update["path"]] = update.get("value")
                        created = (message.get("createSurface") or {}).get("dataModel")
                        if isinstance(created, dict):
                            for key, value in created.items():
                                data[f"/{key}"] = value
                if kind in KEPT:
                    kept.append(_renamed(event))
            turn["events"] = kept
            turns.append(turn)
            print(f"   {sum(1 for e in kept if e['type'] == 'ui')} surface event(s)", file=sys.stderr)

    return {
        "about": (
            "A real conversation with this agent, recorded by tools/sample/record.py "
            "and replayed on a first visit. Regenerate rather than edit."
        ),
        "recorded": dt.date.today().isoformat(),
        "model": served or meta.get("defaultModel") or meta.get("model"),
        "trip": trip,
        "turns": turns,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="http://127.0.0.1:8080")
    parser.add_argument("--out", type=pathlib.Path, default=OUT)
    args = parser.parse_args()
    recording = record(args.base)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(recording, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {args.out.relative_to(ROOT)}: {len(recording['turns'])} turns", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
