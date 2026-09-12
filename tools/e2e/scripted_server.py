"""The real server, with a scripted model in place of Gemini.

Every other piece is the real one — the real agent events, the real surface
passes, the real catalog, the real SSE transport, the real static mounts. Only
`stream_interaction` is replaced, and only because the alternative is an end-to-
end test that needs an API key and costs money to run, which means it does not
run.

The script is deliberately a *whole turn* rather than a single surface: prose,
then a tool call, then more prose and the answer. That shape is what the browser
tests are actually about — whether the interface paints while the model is still
writing, and whether the skeleton goes out before the tool runs.

    python tools/e2e/scripted_server.py [port]
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any, AsyncIterator

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "apps" / "server" / "src"))

from travel_a2ui.doors import interactions
from travel_a2ui import gemini# noqa: E402
from travel_a2ui.gemini import InteractionResult, ToolCall, Usage  # noqa: E402

A2UI_OPEN = "<a2ui>"
A2UI_CLOSE = "</a2ui>"

#: What the fake model says, in order, one entry per round.
#:
#: Round one: a sentence, then a flight search. Round two: a sentence and the
#: surface. The gap between them is where the skeleton and the fill belong.
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
            '\nsurface("inline-1")\n',
            'head = Text("Flights to Madrid", variant="h3")\n',
            "row = FlightOption($airline, $departTime, $arriveTime, $origin, $destination, "
            '$price, Event("select_flight", {id: $id, price: $price}), duration=$duration, '
            "stops=$stops, flightNumber=$flightNumber)\n",
            "list = List(_template($/flights, row))\n",
            'foot = Text("Sample data", variant="caption")\n',
            "root = Column([head, list, foot])\n",
            A2UI_CLOSE,
            " Tap one and I will hold it.",
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


# Patched on the module the agent imported it from, because that is the
# reference the loop actually calls.
interactions.stream_interaction = scripted
gemini.stream_interaction = scripted

from travel_a2ui.doors.http import app  # noqa: E402


@app.post("/__test__/reset")
async def reset_script() -> dict[str, bool]:
    """Lets a test run more than one turn from the top of the script."""
    _reset()
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8130
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
