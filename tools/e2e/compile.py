#!/usr/bin/env python3
"""Compiles the browser suites' canned Express with the A2UI SDK, the way the server does.

`chat.mjs` and `interaction.mjs` stage turns by intercepting `/api/chat` and
answering with A2UI. They used to compile that A2UI themselves with
`packages/express`, a TypeScript port of the compiler — so the browser tests
were testing what the port produced, and the port has gone. This is the
server's own pipeline instead: the SDK's `ExpressParser`, the macros, and the
finishing passes, so a canned turn is exactly what a real one would be.

Reads JSON from stdin:

    [{"surfaceId": "inline-1", "source": "...", "partialAt": 320}, ...]

and writes, in the same order:

    [{"messages": [...], "partial": [...] | null}, ...]

`partialAt`, when given, also compiles the block cut off at that many
characters, as a stream delivers it mid-constructor.
"""

from __future__ import annotations

import json
import pathlib
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "apps" / "server" / "src"))

from travel_a2ui.brain.catalog import parser_for  # noqa: E402
from travel_a2ui.brain.express import as_wire  # noqa: E402
from travel_a2ui.brain.finishing import finish  # noqa: E402
from travel_a2ui.brain.macros import expand  # noqa: E402


def compiled(surface_id: str, source: str, *, final: bool = True) -> list:
    messages = parser_for(surface_id).compile(source, is_final=final)
    return finish(as_wire(expand(messages, {}, {}, "USD")), {})


def main() -> int:
    out = []
    for fixture in json.load(sys.stdin):
        surface_id, source = fixture["surfaceId"], fixture["source"]
        cut = fixture.get("partialAt")
        partial = None
        if isinstance(cut, int):
            try:
                partial = compiled(surface_id, source[:cut], final=False)
            except Exception:  # noqa: BLE001 - half a block may not compile yet, which is fine
                partial = None
        out.append({"messages": compiled(surface_id, source), "partial": partial})
    json.dump(out, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
