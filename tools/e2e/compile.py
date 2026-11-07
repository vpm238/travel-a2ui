#!/usr/bin/env python3
"""Reads the browser suites' canned Express the way a turn reads the model.

`chat.mjs` and `interaction.mjs` stage turns by intercepting `/api/chat` and
answering with A2UI. That A2UI comes from the server's own pipeline
(`brain/ui.py`): the SDK processor, the macros, and the mirror of the renderer
that validates every message, so a canned turn is what a real one sends.

Reads JSON from stdin:

    [{"surfaceId": "inline-1", "source": "...", "partialAt": 320}, ...]

and writes, in the same order:

    [{"messages": [...], "partial": [...] | null}, ...]

`partialAt`, when given, also reads the block cut off at that many characters,
as a stream delivers it mid-line: the messages the processor emits by then.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "apps" / "server" / "src"))

from travel_a2ui.brain import data  # noqa: E402
from travel_a2ui.brain.ui import Canvas, Drawing  # noqa: E402


def _values(_surface: str) -> dict:
    return data.session_values({}, None)


def read(surface_id: str, source: str, *, cut: int | None = None) -> list:
    drawing = Drawing(Canvas(), surface_id, _values)
    text = f"<a2ui>\n{source}\n</a2ui>"
    events = drawing.feed(text[: cut + len("<a2ui>\n")] if cut is not None else text)
    if cut is None:
        events += drawing.close()
    refused = [event[1] for event in events if event[0] == "rejected"]
    if refused and cut is None:
        raise SystemExit(f"{surface_id}: {refused[0]}")
    return [message for event in events if event[0] == "ui" for message in event[2]]


def main() -> int:
    out = []
    for fixture in json.load(sys.stdin):
        surface_id, source = fixture["surfaceId"], fixture["source"]
        cut = fixture.get("partialAt")
        partial = read(surface_id, source, cut=cut) if isinstance(cut, int) else None
        out.append({"messages": read(surface_id, source), "partial": partial or None})
    json.dump(out, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
