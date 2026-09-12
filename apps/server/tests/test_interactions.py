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

from travel_a2ui.doors.interactions import (
    FALLBACK_MODEL,
    SurfaceAction,
    TurnRequest,
    run_turn,
    run_turn_collected,
)
from travel_a2ui.gemini import GeminiError, InteractionResult, ToolCall, Usage
from travel_a2ui.brain.providers.fixture import FixtureProvider

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
        # The turn's own text comes last, under the volatile half of the prompt
        # — today, the surface, the trip so far — which now rides with the
        # message rather than being re-sent as a system instruction.
        assert sent.endswith("actually, make it Lisbon")


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
        from travel_a2ui.brain import trip as trip_model

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

    def test_a_broken_block_in_a_round_that_called_tools_is_reported_too(self) -> None:
        """The hole: the repair branch only ran when the model had stopped.

        A first turn usually draws *and* looks something up in the same round.
        The compile failure was recorded, the tool results went back on their
        own, and the model was never told — so the traveller got a turn with a
        gap in it and nothing ever tried again.

        The complaint goes back as another function result, which is the list
        the model is already reading to decide what to do next.
        """
        import asyncio
        import json

        broken = f'{A2UI_OPEN}\nroot = NoSuchComponent("x")\n{A2UI_CLOSE}'
        model = FakeModel(
            [
                ([broken], [ToolCall(id="c1", name="get_destination", args={"destination": "Madrid"})]),
                ([SURFACE], []),
            ]
        )
        events = asyncio.run(collect(base(message="hi", client=model)))

        assert any(event["type"] == "retry" for event in events)
        assert len(model.bodies) == 2
        sent = model.bodies[1]["input"]
        complaint = next(
            (
                entry
                for entry in sent
                if entry.get("name") == "render_a2ui_express"
            ),
            None,
        )
        assert complaint, "the model was told what the lookup found and nothing else"
        said = json.loads(complaint["result"][0]["text"])
        assert said["ok"] is False
        assert "NoSuchComponent" in said["error"]
        assert "NoSuchComponent" in said["block"]


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

        from travel_a2ui.doors.interactions import _today

        theirs = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        assert _today({"today": theirs}) == theirs

    def test_a_date_no_timezone_could_produce_is_ignored(self) -> None:
        """Untrusted input. A day either side covers every real zone."""
        import datetime as dt

        from travel_a2ui.doors.interactions import _today

        here = dt.date.today().isoformat()
        assert _today({"today": "2019-01-01"}) == here
        assert _today({"today": "not-a-date"}) == here
        assert _today({"today": 7}) == here
        assert _today({}) == here
        assert _today(None) == here


class TestTheSetupIsSentOnce:
    """The Interactions API is stateful, and this app was paying as if it were not.

    Measured against the real API on a 5,411-token system instruction: a
    follow-up carrying `previous_interaction_id` and no `system_instruction`
    cost 44 input tokens instead of 5,411, with `total_cached_tokens` at 0
    throughout — so nothing was quietly caching it either. This app's stable
    half is about thirteen thousand tokens, and it was going out on every round
    of every turn.
    """

    def test_a_fresh_conversation_sends_the_setup(self) -> None:
        import asyncio

        model = FakeModel([([], [])])
        asyncio.run(collect(base(message="hi", client=model)))
        assert model.bodies[0]["system_instruction"].startswith("You are a travel agent")

    def test_a_continued_conversation_does_not(self) -> None:
        import asyncio

        model = FakeModel([([], [])])
        asyncio.run(collect(base(message="hi", interaction_id="int_1", client=model)))
        assert "system_instruction" not in model.bodies[0]
        assert model.bodies[0]["previous_interaction_id"] == "int_1"

    def test_what_changes_every_turn_still_arrives_every_turn(self) -> None:
        """The half that is not sent is the half that never changes.

        Today's date, which surface to draw into and what has been decided move
        with each turn, so they ride in with the message. A model told ten turns
        ago to draw into `inline-1` would still be drawing into `inline-1`.
        """
        import asyncio

        model = FakeModel([([], [])])
        asyncio.run(
            collect(
                base(
                    message="hi",
                    interaction_id="int_1",
                    surface_id="inline-9",
                    trip={"destination": "Madrid"},
                    client=model,
                )
            )
        )
        said = model.bodies[0]["input"][0]["content"][0]["text"]
        assert "inline-9" in said
        assert "Madrid" in said

    def test_a_different_setup_starts_a_new_conversation(self) -> None:
        """Change the skill and the rules are different; the chain is dropped.

        Continuing would mean answering against a contract nobody is reading any
        more — the model's history holds the old skill and nothing would ever
        say otherwise.
        """
        import asyncio

        model = FakeModel([([], [])])
        asyncio.run(
            collect(
                base(
                    message="hi",
                    interaction_id="int_1",
                    setup="a-setup-from-another-skill",
                    client=model,
                )
            )
        )
        assert "previous_interaction_id" not in model.bodies[0]
        assert model.bodies[0]["system_instruction"]

    def test_the_same_setup_continues(self) -> None:
        import asyncio

        from travel_a2ui.doors.interactions import CATALOG_ID
        from travel_a2ui.brain.skills import build_prompt_parts
        import hashlib

        stable, _ = build_prompt_parts(
            variant="express-modular",
            surface="inline",
            surface_id="inline-1",
            catalog_id=CATALOG_ID,
            trip={},
            today="2027-03-01",
        )
        setup = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]

        model = FakeModel([([], [])])
        asyncio.run(
            collect(base(message="hi", interaction_id="int_1", setup=setup, client=model))
        )
        assert model.bodies[0]["previous_interaction_id"] == "int_1"
        assert "system_instruction" not in model.bodies[0]


class TestWhatTheHostAlreadyDrew:
    """The card that appeared with flights in it and then emptied itself.

    The host draws the results the moment the lookup starts and fills them when
    it lands. The model knew nothing about that, so it composed its own tree
    over the same surface, bound to its own paths — and the renderer merges
    components by id, so the filled rows stayed in the data model with nothing
    pointing at them. Real flights, then an empty card, while the traveller was
    looking at it.
    """

    def test_the_tool_result_says_it_is_already_on_screen(self) -> None:
        import asyncio
        import json

        from travel_a2ui.gemini import ToolCall

        model = FakeModel(
            [
                (
                    [],
                    [
                        ToolCall(
                            id="c1",
                            name="search_flights",
                            args={"destination": "Madrid"},
                        )
                    ],
                ),
                ([SURFACE], []),
            ]
        )
        asyncio.run(
            collect(
                base(
                    message="flights to madrid",
                    trip={
                        "destination": "Madrid",
                        "origin": "JFK",
                        "startDate": "2027-04-12",
                        "endDate": "2027-04-19",
                        "travelers": 2,
                    },
                    client=model,
                )
            )
        )

        sent = model.bodies[1]["input"]
        result = next(entry for entry in sent if entry.get("name") == "search_flights")
        said = json.loads(result["result"][0]["text"])
        assert said["alreadyOnScreen"]["path"] == "/flights"
        assert said["alreadyOnScreen"]["rows"] > 0
        assert "Do not draw this surface again" in said["alreadyOnScreen"]["note"]
        # And the flights themselves are still there to talk about.
        assert said.get("items") or said.get("flights")


class TestABusyModelDegradesRatherThanDies:
    """"Currently experiencing high demand" must not end a conversation.

    Measured on the eval that chose the default model: twelve of thirty-six
    turns on Flash 3.8 came back with no surface at all, every one of them a
    capacity spike on Google's side rather than anything the surface got wrong.
    Every turn that actually ran drew the right thing. A traveller halfway
    through planning a trip cannot do anything about that, and an error banner
    is a worse answer than a smaller model's interface.
    """

    class Busy(FakeModel):
        """Refuses `refusals` times, then answers — recording each model asked."""

        def __init__(self, refusals: int, status: int, turns) -> None:  # noqa: ANN001
            super().__init__(turns)
            self.refusals = refusals
            self.status = status
            self.asked: list[str] = []

        async def create(self, **body: Any):  # noqa: ANN201
            self.asked.append(str(body.get("model")))
            if self.refusals > 0:
                self.refusals -= 1
                # Retryable exactly as the real classifier judges it: capacity
                # and rate limits, not a rejected key.
                raise GeminiError(
                    "high demand", self.status, self.status >= 500 or self.status == 429
                )
            return await super().create(**body)

    def _run(self, client) -> list[dict[str, Any]]:  # noqa: ANN001
        import asyncio

        return asyncio.run(
            collect(
                TurnRequest(
                    api_key="k",
                    model="gemini-3.8-flash",
                    message="hello",
                    provider=FixtureProvider(),
                    client=client,
                )
            )
        )

    def test_a_spike_that_clears_is_never_seen(self) -> None:
        client = self.Busy(1, 503, [(["Hi."], [])])
        events = self._run(client)

        assert not [event for event in events if event["type"] == "error"]
        assert client.asked == ["gemini-3.8-flash", "gemini-3.8-flash"], "retried, same model"
        assert not [event for event in events if event["type"] == "served_by"], "nothing to say"

    def test_a_spike_that_lasts_falls_back_and_says_so(self) -> None:
        client = self.Busy(3, 503, [(["Hi."], [])])
        events = self._run(client)

        assert not [event for event in events if event["type"] == "error"]
        assert client.asked[-1] == FALLBACK_MODEL, "answered by the model that was up"
        said = [event for event in events if event["type"] == "served_by"]
        assert said and said[0]["model"] == FALLBACK_MODEL, "a swap the traveller is told about"

    def test_a_rejected_key_fails_immediately_on_the_model_asked_for(self) -> None:
        """A second model will not make a bad key good, and trying is confusing."""
        client = self.Busy(3, 401, [(["Hi."], [])])
        events = self._run(client)

        assert [event for event in events if event["type"] == "error"], "said once, plainly"
        assert client.asked == ["gemini-3.8-flash"], "asked once, not four times"
