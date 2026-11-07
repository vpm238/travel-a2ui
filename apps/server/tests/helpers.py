"""What several test files share: a scripted model, and the pipeline in one call."""

from __future__ import annotations

import json
import json as _json
from typing import Any

from travel_a2ui.brain import data
from travel_a2ui.brain.ui import Canvas, Drawing


class FakeModel:
    """A model that says what it was told to say.

    Scripted per turn: each entry is `(chunks, tool_calls)`, consumed in order,
    so a test can describe "answer, call a tool, then answer again" as data.
    """

    def __init__(self, turns: list[tuple[list[str], list[ToolCall]]]) -> None:
        self.turns = list(turns)
        self.bodies: list[dict[str, Any]] = []

    @property
    def aio(self):  # noqa: ANN201 - shaped like the SDK client, not typed like it
        return self

    @property
    def interactions(self):  # noqa: ANN201
        return self

    async def create(self, **body: Any):  # noqa: ANN201
        self.bodies.append(body)
        chunks, calls = self.turns.pop(0) if self.turns else ([], [])
        model = self

        class Stream:
            def __aiter__(self):  # noqa: ANN204
                return self._events()

            async def _events(self):  # noqa: ANN202
                yield {
                    "event_type": "interaction.created",
                    "interaction": {"id": f"int_{len(model.bodies)}", "status": "in_progress"},
                }
                for chunk in chunks:
                    yield {
                        "event_type": "step.delta",
                        "index": 0,
                        "delta": {"type": "text", "text": chunk},
                    }
                # The signature rides on the round's thought step, ahead of the
                # calls it signs — which is where the API puts it, and the only
                # place a replayed call can get one from.
                signed = next((c.signature for c in calls if c.signature), None)
                if signed:
                    yield {
                        "event_type": "step.delta",
                        "index": 0,
                        "delta": {"type": "thought_signature", "signature": signed},
                    }
                for index, call in enumerate(calls, start=1):
                    yield {
                        "event_type": "step.start",
                        "index": index,
                        "step": {"type": "function_call", "id": call.id, "name": call.name},
                    }
                    # Split across two deltas, because that is how they arrive.
                    text = _json.dumps(call.args)
                    yield {
                        "event_type": "step.delta",
                        "index": index,
                        "delta": {"type": "arguments_delta", "arguments": text[: len(text) // 2]},
                    }
                    yield {
                        "event_type": "step.delta",
                        "index": index,
                        "delta": {"type": "arguments_delta", "arguments": text[len(text) // 2 :]},
                    }
                    yield {"event_type": "step.stop", "index": index}
                yield {
                    "event_type": "interaction.completed",
                    "interaction": {
                        "id": f"int_{len(model.bodies)}",
                        "status": "completed",
                        "usage": {
                            "total_input_tokens": 100,
                            "total_output_tokens": 20,
                            "total_cached_tokens": 80,
                            "total_thought_tokens": 5,
                        },
                    },
                }

        return Stream()


def drawn(express: str, surface_id: str = "inline-1", trip: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Express, read and expanded the way a turn reads it: the wire messages."""
    values = lambda _s: data.session_values(trip or {}, None)  # noqa: E731
    drawing = Drawing(Canvas(), surface_id, values)
    events = [*drawing.feed(f"<a2ui>\n{express}\n</a2ui>"), *drawing.close()]
    refused = [event[1] for event in events if event[0] == "rejected"]
    assert not refused, refused
    return [message for event in events if event[0] == "ui" for message in event[2]]


A2UI_OPEN = "<a2ui>"
A2UI_CLOSE = "</a2ui>"

SETTLED = {
    "destination": "Madrid",
    "origin": "JFK",
    "startDate": "2027-04-12",
    "endDate": "2027-04-19",
    "travelers": 2,
}

#: A surface that asks for the boundaries, as the brief draws it.
ASKING = (
    f"{A2UI_OPEN}\n"
    'surface("inline-1", sendDataModel=true)\n'
    'when = DateRangePicker("Travel dates", $/trip/startDate, $/trip/endDate)\n'
    'who = TravelerCounter("Travellers", $/trip/travelers)\n'
    'lbl = Text("Search flights")\n'
    'go = Button(lbl, "primary", Event("find_flights"))\n'
    "root = Column([when, who, go])\n"
    f"{A2UI_CLOSE}"
)


def base(**overrides: Any):
    """A turn request with no key, no network and the fixture provider."""
    from travel_a2ui.brain.providers.fixture import FixtureProvider
    from travel_a2ui.doors.interactions import TurnRequest

    defaults: dict[str, Any] = {
        "api_key": "not-a-real-key",
        "model": "gemini-3-pro-preview",
        "provider": FixtureProvider(),
    }
    defaults.update(overrides)
    return TurnRequest(**defaults)


def events_of(request) -> list[dict[str, Any]]:
    import asyncio

    from travel_a2ui.doors.interactions import run_turn

    async def drain() -> list[dict[str, Any]]:
        return [event async for event in run_turn(request)]

    return asyncio.run(drain())


def messages_of(events: list[dict[str, Any]], surface_id: str | None = None) -> list[dict[str, Any]]:
    return [
        message
        for event in events
        if event["type"] == "ui" and (surface_id is None or event["surfaceId"] == surface_id)
        for message in event["messages"]
    ]


def said_to_model(model: "FakeModel", body: int) -> str:
    """Everything the turn sent the model in one request, as text."""
    return json.dumps(model.bodies[body].get("input"), ensure_ascii=False)
