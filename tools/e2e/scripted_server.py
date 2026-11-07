"""The real server, with a scripted model in place of Gemini.

Every other piece is the real one: the real turn loop, the real A2UI
processor and macros, the real catalog, the real SSE transport, the real
static mounts. Only
`stream_interaction` is replaced, and only because the alternative is an end-to-
end test that needs an API key and costs money to run, which means it does not
run.

The script is deliberately a *whole turn* rather than a single surface: prose,
then a tool call, then more prose and the answer. That shape is what the browser
tests are actually about — whether the interface paints while the model is still
writing, and whether a lookup's rows are filed where the brief says they land.

    python tools/e2e/scripted_server.py [port]
"""

from __future__ import annotations

import os
import pathlib
import sys
from typing import Any, AsyncIterator

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "apps" / "server" / "src"))

# A test starts from an empty conversation unless it asks for the sample trip.
os.environ.setdefault("SAMPLE_TRIP", "0")
# A test server answers every suite on the shared (scripted) key.
os.environ.setdefault("SHARED_KEY_TURNS_PER_HOUR", "1000000")

from travel_a2ui import gemini  # noqa: E402
from travel_a2ui.doors import interactions
from travel_a2ui.gemini import InteractionResult, ToolCall, Usage  # noqa: E402

A2UI_OPEN = "<a2ui>"
A2UI_CLOSE = "</a2ui>"

#: What the fake model says, in order, one entry per round.
#:
#: Round one: a sentence, then a flight search. Round two: a sentence and the
#: surface. The gap between them is where a lookup's rows are filed.
SCRIPT: list[tuple[list[str], list[ToolCall]]] = [
    (
        ["Looking at flights to Madrid now. "],
        [
            ToolCall(
                id="call-1",
                name="search_flights",
                args={"destination": "Madrid", "origin": "JFK", "date": "2099-04-12"},
            )
        ],
    ),
    (
        [
            "Here are four, cheapest first. ",
            A2UI_OPEN,
            '\nhead = Text("### Flights to Madrid")\n',
            'fares = Flights(_, "/trip/selectedFlight")\n',
            'foot = Text("Sample data", variant="caption")\n',
            "root = Column([head, fares, foot])\n",
            A2UI_CLOSE,
            " Tap one and I will hold it.",
        ],
        [],
    ),
    # Round three answers a fare press: the host has already recorded the fare.
    (
        ["Holding that one. "],
        [
            ToolCall(
                id="call-2",
                name="save_trip",
                args={"destination": "Madrid", "origin": "JFK", "startDate": "2099-04-12", "travelers": 1},
            )
        ],
    ),
    # And round four puts the trip panel up, which a client's sidebar or cart shows.
    (
        [
            "It is on your trip.",
            A2UI_OPEN,
            '\nsurface("sidebar")\npanel = Trip("Your trip to Madrid", true)\nroot = Column([panel])\n',
            A2UI_CLOSE,
        ],
        [],
    ),
]


async def scripted(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
    """Stands in for `gemini.stream_interaction`."""
    index = scripted.round  # type: ignore[attr-defined]
    scripted.round += 1  # type: ignore[attr-defined]

    chunks, calls = SCRIPT[index] if index < len(SCRIPT) else ([], [])

    for chunk in chunks:
        yield {"type": "text", "delta": chunk}

    yield {
        "type": "result",
        "result": InteractionResult(
            interaction_id=f"int_{index + 1}",
            tool_calls=list(calls),
            text="".join(chunks),
            usage=Usage(input_tokens=100, output_tokens=20, cached_tokens=80),
            status="completed",
        ),
    }


scripted.round = 0  # type: ignore[attr-defined]


def _reset() -> None:
    scripted.round = 0  # type: ignore[attr-defined]


# Patched in every module that holds its own reference to it: `turn` and
# `panels` import the function by name.
from travel_a2ui.doors.interactions import panels as _panels  # noqa: E402
from travel_a2ui.doors.interactions import turn as _turn
from travel_a2ui.doors.interactions import warmup as _warmup


async def background(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
    """A warm-up or a panel draw: answered, and not a round of the script.

    They are calls the app makes on its own, between and after turns, and they
    must not use up the turn the test is about.
    """
    del kwargs
    yield {
        "type": "result",
        "result": InteractionResult(
            interaction_id="int_background",
            tool_calls=[],
            text="",
            usage=Usage(input_tokens=1, output_tokens=0, cached_tokens=0),
            status="completed",
        ),
    }


for _module in (interactions, gemini, _turn):
    _module.stream_interaction = scripted
for _module in (_panels, _warmup):
    _module.stream_interaction = background

from travel_a2ui.doors.http import app  # noqa: E402


@app.post("/__test__/reset")
async def reset_script() -> dict[str, bool]:
    """Lets a test run more than one turn from the top of the script."""
    _reset()
    return {"ok": True}


# Ahead of the static mounts: the client is mounted at `/`, which otherwise
# answers this POST first, with a 405, and the script can never be reset.
app.router.routes.insert(0, app.router.routes.pop())


if __name__ == "__main__":
    import uvicorn

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8130
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
