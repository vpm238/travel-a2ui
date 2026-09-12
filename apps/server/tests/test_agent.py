"""A whole turn, driven off a scripted model stream.

No key and no network: the model is a fake that yields exactly the events a
real one would, which is the only way to assert the things that actually go
wrong in this loop. Those are all about *order* and *when*, and none of them
throws:

  - prose and A2UI arriving interleaved rather than prose-then-everything;
  - the skeleton going out before the tool runs, and the fill after it;
  - a value the traveller set reaching the trip without the model being asked;
  - a date range that ends before it starts being refused rather than saved;
  - the panels being redrawn only when the decisions changed shape.
"""

from __future__ import annotations

from typing import Any

import pytest

from travel_a2ui.agent import SurfaceAction, TurnRequest, run_turn, run_turn_collected
from travel_a2ui.gemini import InteractionResult, ToolCall, Usage
from travel_a2ui.providers.fixture import FixtureProvider

A2UI_OPEN = "<a2ui>"
A2UI_CLOSE = "</a2ui>"


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
                for index, call in enumerate(calls, start=1):
                    yield {
                        "event_type": "step.start",
                        "index": index,
                        "step": {"type": "function_call", "id": call.id, "name": call.name},
                    }
                    # Split across two deltas, because that is how they arrive
                    # and reassembling them is where this used to be wrong.
                    import json as _json

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


SURFACE = (
    f"{A2UI_OPEN}\n"
    'surface("inline-1")\n'
    'head = Text("Madrid in April", variant="h3")\n'
    "root = Column([head])\n"
    f"{A2UI_CLOSE}"
)


async def collect(request: TurnRequest) -> list[dict[str, Any]]:
    return [event async for event in run_turn(request)]


def base(**overrides: Any) -> TurnRequest:
    defaults: dict[str, Any] = {
        "api_key": "not-a-real-key",
        "model": "gemini-3-pro-preview",
        "provider": FixtureProvider(),
        # A shape that already matches means no panel rebuild, which keeps the
        # scripted turns to exactly the ones a test is about.
        "shape": None,
    }
    defaults.update(overrides)
    return TurnRequest(**defaults)


def test_prose_and_a2ui_come_out_separately() -> None:
    import asyncio

    model = FakeModel([(["Here are some ideas. ", SURFACE], [])])
    events = asyncio.run(collect(base(message="Madrid in April", client=model)))

    text = "".join(event["delta"] for event in events if event["type"] == "text")
    ui = [event for event in events if event["type"] == "ui"]
    assert text.strip() == "Here are some ideas."
    assert ui, "the Express block became a surface"
    # And the block itself never reaches the transcript as prose — a traveller
    # reading `surface("inline-1")` in the chat is the failure this splits to
    # prevent.
    assert "surface(" not in text


def test_a_surface_paints_before_the_turn_ends() -> None:
    """The ordering that makes streaming worth doing.

    A UI event before the last text delta means the surface was on screen while
    the model was still typing. Collect-then-emit passes every other assertion
    in this file and fails this one.
    """
    import asyncio

    model = FakeModel([(["First. ", SURFACE, " And after."], [])])
    events = asyncio.run(collect(base(message="hi", client=model)))

    kinds = [event["type"] for event in events if event["type"] in ("text", "ui")]
    assert "ui" in kinds
    assert kinds.index("ui") < len(kinds) - 1, "something was still to come after the surface"


class TestTheSkeleton:
    def test_the_shape_goes_out_before_the_tool_runs(self) -> None:
        import asyncio

        model = FakeModel(
            [
                (
                    ["Looking. "],
                    [ToolCall(id="c1", name="search_flights", args={"destination": "Madrid"})],
                ),
                (["Here they are. ", SURFACE], []),
            ]
        )
        events = asyncio.run(
            collect(
                base(
                    message="flights to Madrid",
                    trip={
                        "origin": "JFK",
                        "destination": "Madrid",
                        "startDate": "2099-04-12",
                        "endDate": "2099-04-19",
                        "travelers": 2,
                    },
                    client=model,
                )
            )
        )

        kinds = [event["type"] for event in events]
        tool_at = kinds.index("tool")
        result_at = kinds.index("tool_result")
        ui_positions = [i for i, kind in enumerate(kinds) if kind == "ui"]

        assert any(tool_at < i < result_at for i in ui_positions), (
            "the layout must paint while the search is running, not after it"
        )
        assert any(i > result_at for i in ui_positions), "and fill once results land"

    def test_the_opening_is_blank_and_the_fill_has_rows(self) -> None:
        import asyncio

        model = FakeModel(
            [
                (
                    [],
                    [ToolCall(id="c1", name="search_flights", args={"destination": "Madrid"})],
                ),
                ([], []),
            ]
        )
        events = asyncio.run(
            collect(
                base(
                    message="flights",
                    trip={
                        "origin": "JFK",
                        "destination": "Madrid",
                        "startDate": "2099-04-12",
                        "endDate": "2099-04-19",
                        "travelers": 2,
                    },
                    client=model,
                )
            )
        )

        kinds = [event["type"] for event in events]
        result_at = kinds.index("tool_result")
        opening = next(e for i, e in enumerate(events) if e["type"] == "ui" and i < result_at)
        fill = next(e for i, e in enumerate(events) if e["type"] == "ui" and i > result_at)

        seed = next(m for m in opening["messages"] if "updateDataModel" in m)
        assert all(row == {} for row in seed["updateDataModel"]["value"])

        filled = fill["messages"][0]["updateDataModel"]["value"]
        assert filled and all(row.get("airline") for row in filled)

    def test_a_tool_with_no_predictable_shape_gets_no_skeleton(self) -> None:
        import asyncio

        model = FakeModel(
            [([], [ToolCall(id="c1", name="get_trip", args={})]), ([], [])]
        )
        events = asyncio.run(collect(base(message="what do you have", client=model)))
        kinds = [event["type"] for event in events]
        tool_at, result_at = kinds.index("tool"), kinds.index("tool_result")
        assert not any(
            kinds[i] == "ui" for i in range(tool_at, result_at)
        ), "nothing to draw, so nothing is drawn"


class TestWhatTheTravellerSet:
    def test_a_pressed_value_reaches_the_trip_without_asking_the_model(self) -> None:
        """The host records it; the model is not depended on to notice.

        That dependency is what made a second card forget what the first asked.
        """
        import asyncio

        model = FakeModel([([], [])])
        events = asyncio.run(
            collect(
                base(
                    action=SurfaceAction(
                        name="search_flights",
                        surface_id="inline-1",
                        context={"origin": "BOS", "travelers": 3},
                    ),
                    client=model,
                )
            )
        )
        trip = next(e for e in reversed(events) if e["type"] == "trip")["trip"]
        assert trip["origin"] == "BOS"
        assert trip["travelers"] == 3

    def test_pressing_settles_a_value_the_agent_had_guessed(self) -> None:
        import asyncio

        model = FakeModel([([], [])])
        events = asyncio.run(
            collect(
                base(
                    trip={"destination": "Madrid", "travelers": 2, "assumed": ["travelers"]},
                    action=SurfaceAction(
                        name="commit_surface",
                        surface_id="inline-1",
                        context={"travelers": 2},
                    ),
                    client=model,
                )
            )
        )
        trip = next(e for e in reversed(events) if e["type"] == "trip")["trip"]
        assert "travelers" not in (trip.get("assumed") or []), (
            "pressing the button is the traveller saying so, however the value got there"
        )

    def test_dates_that_end_before_they_start_are_refused(self) -> None:
        """`save_trip` always validated; a button press did not.

        A picker handing back 20 April → 12 April priced four flights against a
        trip with negative nights, and the surface looked entirely fine doing it.
        """
        import asyncio

        model = FakeModel([([], [])])
        request = base(
            trip={"destination": "Madrid", "startDate": "2099-04-01", "endDate": "2099-04-08"},
            action=SurfaceAction(
                name="commit_surface",
                surface_id="inline-1",
                context={"startDate": "2099-04-20", "endDate": "2099-04-12"},
            ),
            client=model,
        )
        events = asyncio.run(collect(request))

        trip = next(e for e in reversed(events) if e["type"] == "trip")["trip"]
        # Reverted to what was saved, not deleted: losing a value they had
        # already agreed to is a second wrong answer.
        assert trip["startDate"] == "2099-04-01"
        assert trip["endDate"] == "2099-04-08"

        # And the model is told, or it reads back the old trip and says nothing.
        sent = model.bodies[0]["input"][0]["content"][0]["text"]
        assert "Refused" in sent

    def test_typing_beats_pressing_when_both_arrive(self) -> None:
        import asyncio

        model = FakeModel([([], [])])
        asyncio.run(
            collect(
                base(
                    message="actually, make it Lisbon",
                    action=SurfaceAction(
                        name="search_flights",
                        surface_id="inline-1",
                        context={"origin": "BOS"},
                    ),
                    client=model,
                )
            )
        )
        sent = model.bodies[0]["input"][0]["content"][0]["text"]
        assert sent.startswith("actually, make it Lisbon")


class TestThePanel:
    def test_a_press_on_the_panel_is_read_as_a_request_to_re_ask(self) -> None:
        import asyncio

        model = FakeModel([([], [])])
        asyncio.run(
            collect(
                base(
                    action=SurfaceAction(
                        name="change", surface_id="sidebar", context={"field": "selectedFlight"}
                    ),
                    trip={"destination": "Madrid"},
                    client=model,
                )
            )
        )
        sent = model.bodies[0]["input"][0]["content"][0]["text"]
        assert "selectedFlight" in sent
        assert "ask for it again inline" in sent

    def test_the_panels_are_brought_up_to_date_every_turn(self) -> None:
        import asyncio

        model = FakeModel([([], [])])
        events = asyncio.run(
            collect(base(message="hi", trip={"destination": "Madrid"}, client=model))
        )
        panels = {
            event["surfaceId"]
            for event in events
            if event["type"] == "ui" and event["surfaceId"] in ("sidebar", "home")
        }
        assert panels == {"sidebar", "home"}

    def test_an_unchanged_shape_does_not_cost_a_redraw(self) -> None:
        """One extra model turn, and only when the decisions moved."""
        import asyncio
        from travel_a2ui import trip as trip_model

        trip = {"destination": "Madrid", "origin": "JFK"}
        model = FakeModel([([], [])])
        asyncio.run(
            collect(
                base(
                    message="hi",
                    trip=trip,
                    shape=trip_model.decision_shape(trip),
                    client=model,
                )
            )
        )
        assert len(model.bodies) == 1, "the turn itself, and no panel rebuild"

    def test_a_changed_shape_redraws_both_panels(self) -> None:
        import asyncio

        model = FakeModel([([], []), ([], []), ([], [])])
        asyncio.run(
            collect(
                base(
                    message="hi",
                    trip={"destination": "Madrid", "origin": "JFK"},
                    shape="something-else",
                    client=model,
                )
            )
        )
        assert len(model.bodies) == 3, "the turn, then the sidebar and the home screen"
        # Not chained: a rebuild is not something the traveller said.
        assert "previous_interaction_id" not in model.bodies[1]

    def test_nothing_is_redrawn_before_there_is_a_trip(self) -> None:
        import asyncio

        model = FakeModel([([], [])])
        asyncio.run(collect(base(message="hi", shape="moved", client=model)))
        assert len(model.bodies) == 1, "a panel saying 'no trip' is a panel nobody wants"


class TestTheConversation:
    def test_the_chain_is_threaded_so_a_turn_sends_one_message(self) -> None:
        import asyncio

        model = FakeModel([([], [])])
        asyncio.run(collect(base(message="hi", interaction_id="int_previous", client=model)))
        assert model.bodies[0]["previous_interaction_id"] == "int_previous"
        assert len(model.bodies[0]["input"]) == 1, "one message, not the whole transcript"

    def test_the_result_carries_the_new_interaction_id(self) -> None:
        import asyncio

        model = FakeModel([([], [])])
        events = asyncio.run(collect(base(message="hi", client=model)))
        result = next(e for e in events if e["type"] == "__result__")["result"]
        assert result.interaction_id == "int_1"

    def test_tool_results_all_go_back_in_one_request(self) -> None:
        """Which is what keeps the model calling tools in parallel."""
        import asyncio

        model = FakeModel(
            [
                (
                    [],
                    [
                        ToolCall(id="c1", name="get_destination", args={"destination": "Madrid"}),
                        ToolCall(id="c2", name="get_weather", args={"destination": "Madrid"}),
                    ],
                ),
                ([], []),
            ]
        )
        asyncio.run(collect(base(message="tell me about Madrid", client=model)))
        second = model.bodies[1]["input"]
        assert len(second) == 2
        assert {entry["name"] for entry in second} == {"get_destination", "get_weather"}

    def test_a_runaway_tool_loop_stops(self) -> None:
        import asyncio

        call = [ToolCall(id="c", name="get_trip", args={})]
        model = FakeModel([([], call)] * 10)
        events = asyncio.run(collect(base(message="hi", client=model)))
        errors = [e for e in events if e["type"] == "error"]
        assert errors and "rounds of tool calls" in errors[0]["message"]

    def test_usage_is_reported_once_and_not_doubled(self) -> None:
        import asyncio

        model = FakeModel([([], [])])
        events = asyncio.run(collect(base(message="hi", client=model)))
        usage = next(e for e in events if e["type"] == "usage")
        assert usage["inputTokens"] == 100
        assert usage["cacheReadTokens"] == 80
        assert usage["cacheWriteTokens"] == 0, "Gemini caches implicitly; there is no write"


class TestFailures:
    def test_an_api_failure_becomes_a_sentence(self) -> None:
        import asyncio

        class Broken(FakeModel):
            async def create(self, **body: Any):  # noqa: ANN201
                raise RuntimeError("upstream exploded")

        events = asyncio.run(collect(base(message="hi", client=Broken([]))))
        error = next(e for e in events if e["type"] == "error")
        assert error["message"]
        assert isinstance(error["retryable"], bool)

    def test_a_surface_drawn_before_the_failure_is_not_thrown_away(self) -> None:
        """Half an answer beats an error banner over nothing."""
        import asyncio

        class DiesAfterDrawing(FakeModel):
            async def create(self, **body: Any):  # noqa: ANN201
                class Stream:
                    async def __aiter__(self):  # noqa: ANN204
                        yield {
                            "event_type": "step.delta",
                            "index": 0,
                            "delta": {"type": "text", "text": SURFACE},
                        }
                        raise RuntimeError("the connection went away")

                return Stream()

        events = asyncio.run(collect(base(message="hi", client=DiesAfterDrawing([]))))
        assert any(event["type"] == "ui" for event in events)
        assert any(event["type"] == "error" for event in events)

    def test_express_that_does_not_compile_is_reported_back_to_the_model(self) -> None:
        """Once. A model that cannot fix it on the second try will not on the fifth."""
        import asyncio

        broken = f'{A2UI_OPEN}\nroot = NoSuchComponent("x")\n{A2UI_CLOSE}'
        model = FakeModel([([broken], []), ([SURFACE], [])])
        events = asyncio.run(collect(base(message="hi", client=model)))

        assert any(event["type"] == "ui_error" for event in events)
        assert any(event["type"] == "retry" for event in events)
        assert len(model.bodies) == 2
        assert "did not compile" in model.bodies[1]["input"][0]["content"][0]["text"]


def test_run_turn_collected_gathers_the_same_turn() -> None:
    """What MCP uses, which has no stream to write into."""
    import asyncio

    model = FakeModel([(["Here. ", SURFACE], [])])
    out = asyncio.run(
        run_turn_collected(base(message="hi", trip={"destination": "Madrid"}, client=model))
    )
    assert out["text"] == "Here."
    assert out["ui"]
    assert out["trip"]["destination"] == "Madrid"
    assert out["interactionId"] == "int_1"


class TestWhatDayItIs:
    """The container is in UTC; the traveller is holding a different calendar.

    At 18:00 in Los Angeles the server has already turned the page, so
    "tomorrow" came back a day late and "this Saturday" was the wrong Saturday.
    The browser is the only party that knows which day it is for them.
    """

    def test_the_browser_s_date_wins(self) -> None:
        import datetime as dt

        from travel_a2ui.agent import _today

        theirs = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        assert _today({"today": theirs}) == theirs

    def test_a_date_no_timezone_could_produce_is_ignored(self) -> None:
        """Untrusted input. A day either side covers every real zone."""
        import datetime as dt

        from travel_a2ui.agent import _today

        here = dt.date.today().isoformat()
        assert _today({"today": "2019-01-01"}) == here
        assert _today({"today": "not-a-date"}) == here
        assert _today({"today": 7}) == here
        assert _today({}) == here
        assert _today(None) == here
