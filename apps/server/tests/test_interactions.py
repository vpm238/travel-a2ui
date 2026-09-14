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


#: A trip with its boundaries settled, so a turn is not blocked on anything.
#:
#: `asks_nothing` rejects a surface drawn while the trip is waiting on route,
#: dates or party that asks for none of them — which is right, and which every
#: test using `SURFACE` would otherwise trip over, because `SURFACE` is a
#: heading in a column and asks for nothing at all. A test about prose and
#: Express coming out separately should not also be a test about that.
SETTLED = {
    "destination": "Madrid",
    "origin": "JFK",
    "startDate": "2027-04-12",
    "endDate": "2027-04-19",
    "travelers": 2,
}


#: A surface that asks for the boundaries — what a blocked turn owes.
ASKING = (
    f"{A2UI_OPEN}\n"
    'surface("inline-1")\n'
    'when = DateRangePicker("Travel dates", $/trip/startDate, $/trip/endDate)\n'
    'who = TravelerCounter("Going out", $/trip/travelers)\n'
    'lbl = Text("Search flights")\n'
    'go = Button(lbl, "primary", Event("search", {startDate: $/trip/startDate}))\n'
    "root = Column([when, who, go])\n"
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

    def test_a_changed_shape_redraws_the_sidebar_and_not_the_home_screen(self) -> None:
        """A chat turn rebuilds one panel, not two.

        The home screen used to be rebuilt beside the sidebar on every shape
        change — a second model call, in parallel, for a surface the traveller
        is not looking at while they are in the conversation. And it is a
        *summary*: rebuilding it mid-conversation means composing a dashboard of
        a trip that is still being decided, which is how `StatTile`,
        `ProgressMeter` and `MapPreview` ended up in front of a model that
        needed a date picker.

        It is built when somebody asks for it now. See `surface.py`.
        """
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
        assert len(model.bodies) == 2, "the turn, then the sidebar — and nothing else"
        # Not chained: a rebuild is not something the traveller said.
        assert "previous_interaction_id" not in model.bodies[1]

    def test_the_home_screen_is_still_drawable_on_request(self) -> None:
        """Out of the turn loop, not out of the product."""
        import asyncio

        model = FakeModel([([SURFACE], [])])
        events = asyncio.run(
            collect(
                base(
                    message="build my home page",
                    surface="home",
                    surface_id="home",
                    trip=dict(SETTLED),
                    shape=__import__(
                        "travel_a2ui.brain.trip", fromlist=["decision_shape"]
                    ).decision_shape(SETTLED),
                    client=model,
                )
            )
        )
        drawn = [event["surfaceId"] for event in events if event["type"] == "ui"]
        assert "home" in drawn, "asking for the home screen has to draw one"
        # The sidebar appears too, and that is not a rebuild: a value the
        # traveller set reaches every standing surface as a data-model update,
        # with no model in the path. One model call, which is the turn itself.
        assert len(model.bodies) == 1, f"extra model calls: {len(model.bodies)}"

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
        model = FakeModel([([broken], []), ([ASKING], [])])
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
                ([ASKING], []),
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
        run_turn_collected(base(message="hi", trip=dict(SETTLED), client=model))
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
    A traveller halfway through planning a trip cannot do anything about that,
    and an error banner is a worse answer than a smaller model's interface.
    This covers a model that is busy when asked; `TestTheModelDropsTheStream
    MidSentence` covers the commoner case of one that goes busy while
    answering.
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


def test_a_surface_written_as_json_never_reaches_the_traveller() -> None:
    """The model reached for a notation that does not exist, and it was printed.

    Reported from a real turn: asked for a trip from SFO to NYC, the reply was
    a fenced JSON document — `"call": "host:render"`, components typed `Form`
    and `NumberField` — and the whole thing appeared in the chat as prose,
    because the splitter looks for `<a2ui>` and there was none to find.

    A compile error was already caught and handed back to be rewritten. This
    was the same mistake one step earlier and the only one that reached the
    screen, which made it the worst of the three.
    """
    import asyncio

    misdrawn = (
        "Here are your options.\n\n"
        '```json\n[{"call": "host:render", "surface": "inline-1", '
        '"components": [{"id": "picker", "type": "Form"}]}]\n```\n\nLet me know.'
    )
    model = FakeModel([(list(misdrawn), []), (["Sorry — ", ASKING], [])])
    events = asyncio.run(collect(base(message="plan me a trip", client=model)))

    text = "".join(event["delta"] for event in events if event["type"] == "text")
    assert "host:render" not in text, "the JSON was printed at the traveller"
    assert '"components"' not in text
    assert "Here are your options." in text, "the prose around it still arrives"

    # And the model is told, once, the way a compile failure tells it.
    retries = [event for event in events if event["type"] == "retry"]
    assert retries, "the model was never told it used the wrong notation"
    assert "Express" in retries[0]["reason"]

    told = model.bodies[-1]["input"][0]["content"][0]["text"]
    assert "<a2ui>" in told, "the retry has to name the notation that does work"
    assert "host:render" in told, "and quote back what it actually wrote"

    # The second attempt is the one the traveller sees.
    assert [event for event in events if event["type"] == "ui"], "the retry drew"


def test_a_fence_is_not_retried_forever() -> None:
    """Twice is a pattern; a third round is a traveller watching a spinner."""
    import asyncio

    misdrawn = '```json\n{"components": []}\n```'
    model = FakeModel([(list(misdrawn), []), (list(misdrawn), [])])
    events = asyncio.run(collect(base(message="plan me a trip", client=model)))

    assert len([event for event in events if event["type"] == "retry"]) == 1
    assert len(model.bodies) == 2, "one retry, not a loop"


def test_a_turn_that_promises_and_draws_nothing_is_handed_back() -> None:
    """"Let me record your multi-city route and get your travel dates."

    Measured on a multi-city opening: four runs of five ended exactly there,
    with no tool called and nothing drawn. The brief forbids it in bold and the
    spoken brief forbids it by name, which is how we know wording is not what
    closes this.
    """
    import asyncio

    model = FakeModel([(["Let me set up your route and get your dates."], []), ([ASKING], [])])
    events = asyncio.run(collect(base(message="plan me a trip to Madrid", client=model)))

    retries = [event for event in events if event["type"] == "retry"]
    assert retries, "the turn ended on a promise and nobody said anything"
    assert "promised" in retries[0]["reason"]
    assert [event for event in events if event["type"] == "ui"], "the second attempt drew"

    told = model.bodies[-1]["input"][0]["content"][0]["text"]
    assert "DateRangePicker" in told, "the nudge names the controls the turn needed"


def test_a_turn_that_did_something_is_left_alone() -> None:
    """The commonest sentence in a good turn starts with "Let me"…"""
    import asyncio

    model = FakeModel([(["Let me show you what I found. ", SURFACE], [])])
    events = asyncio.run(collect(base(message="flights to Madrid", trip=dict(SETTLED), client=model)))

    assert not [event for event in events if event["type"] == "retry"], (
        "it drew a surface; there is nothing to correct"
    )


def test_let_me_know_is_not_a_promise() -> None:
    """…and the commonest way to *end* one is an invitation, not an intention."""
    import asyncio

    model = FakeModel([(["Four nonstops. Let me know if you want the fares."], [])])
    events = asyncio.run(collect(base(message="any nonstops?", client=model)))

    assert not [event for event in events if event["type"] == "retry"], (
        "a turn that answered the question was re-prodded over 'let me know'"
    )


def test_the_promise_nudge_fires_once() -> None:
    """A model that answers a nudge with another promise will not stop at three."""
    import asyncio

    model = FakeModel([(["Let me get that."], []), (["Let me get that."], [])])
    events = asyncio.run(collect(base(message="plan me a trip", client=model)))

    assert len([event for event in events if event["type"] == "retry"]) == 1
    assert len(model.bodies) == 2, "one retry, not a loop"


def test_a_dashboard_drawn_on_a_blocked_turn_is_sent_back() -> None:
    """The surface that looks most like success and helps least.

    Told "plan me a trip from SFO to NYC", the model drew — in separate measured
    runs — six StatTiles and a ProgressMeter, and a MapPreview with six buttons.
    Both compiled. Both validated. Neither contained anywhere to put a date, so
    the traveller had nothing to answer and the turn was spent. A progress meter
    before anything is decided is a bar at zero.
    """
    import asyncio

    dashboard = (
        f"{A2UI_OPEN}\n"
        'surface("inline-1")\n'
        'head = Text("Your trip", variant="h3")\n'
        't1 = StatTile("Booked", "0 of 5")\n'
        "root = Column([head, t1])\n"
        f"{A2UI_CLOSE}"
    )
    model = FakeModel([([dashboard], []), ([ASKING], [])])
    events = asyncio.run(collect(base(message="plan me a trip to Madrid", client=model)))

    retries = [event for event in events if event["type"] == "retry"]
    assert retries, "a surface with nowhere to answer went out as if it helped"
    assert "asks for nothing" in retries[0]["reason"]

    told = model.bodies[-1]["input"][0]["content"][0]["text"]
    assert "startDate" in told, "the retry has to name what the trip is waiting on"

    # And it was *drawn*, not swallowed. Rejecting it outright turned a useless
    # dashboard into an empty screen whenever the retry did not recover —
    # measured over 36 openings, drawing fell from 60% to 47% when this check
    # rejected rather than annotated. A correction must never leave the screen
    # emptier than it found it.
    drawn = [event for event in events if event["type"] == "ui"]
    assert len(drawn) >= 2, "the first surface never reached the traveller"


def test_a_surface_that_asks_for_one_missing_thing_is_fine() -> None:
    """Progress is progress. Asking for the dates without the party is a turn."""
    import asyncio

    dates_only = (
        f"{A2UI_OPEN}\n"
        'surface("inline-1")\n'
        'when = DateRangePicker("When?", $/trip/startDate, $/trip/endDate)\n'
        "root = Column([when])\n"
        f"{A2UI_CLOSE}"
    )
    model = FakeModel([([dates_only], [])])
    events = asyncio.run(collect(base(message="plan me a trip", client=model)))

    assert not [event for event in events if event["type"] == "retry"]
    assert [event for event in events if event["type"] == "ui"]


def test_a_settled_trip_may_draw_whatever_it_likes() -> None:
    """Flight cards answer a question rather than posing one.

    The check must not fire once the boundaries are set, or every result surface
    in the app becomes an error.
    """
    import asyncio

    model = FakeModel([([SURFACE], [])])
    events = asyncio.run(
        collect(
            base(
                message="show me the plan",
                trip=dict(SETTLED),
                shape=__import__(
                    "travel_a2ui.brain.trip", fromlist=["decision_shape"]
                ).decision_shape(SETTLED),
                client=model,
            )
        )
    )
    assert not [event for event in events if event["type"] == "retry"]


def test_a_guessed_date_is_still_owed_a_picker() -> None:
    """The hole the first version of this check fell through.

    `save_trip` takes an `assumed` list for values the model guessed, and its
    contract says the question stays open. But `missing_for` reads a guessed
    date as a date, so a turn could guess "next weekend means the 24th", save
    it, and then draw a dashboard — with the check standing down, because on
    paper nothing was missing.

    That is the trip in the reported screenshot: dates of 24–27 September that
    the traveller never gave, on a panel presented as settled.
    """
    from travel_a2ui.doors.interactions import _still_owed

    guessed = {
        "destination": "NYC",
        "origin": "SFO",
        "startDate": "2026-09-24",
        "assumed": ["startDate"],
    }
    assert _still_owed(guessed) == ["startDate"]

    given = {k: v for k, v in guessed.items() if k != "assumed"}
    assert _still_owed(given) == [], "a date they actually gave is settled"


class TestTheModelDropsTheStreamMidSentence:
    """A capacity failure that arrives *after* the stream opens.

    The retry and the fallback both live in `_open`, which has returned by the
    time the first word is on screen. So a model that goes busy halfway through
    answering went straight past all of it: the turn ended with one dangling
    clause and nothing drawn, and nothing retried because nothing had failed in
    a place that was watching.

    Measured on the opening-turn eval: of eight blank turns re-run with the
    failure printed, six were this, every one after the first few words.
    """

    class Drops(FakeModel):
        """Streams `said`, then fails mid-stream, once. Then answers normally."""

        def __init__(self, said: list[str], turns, calls=()) -> None:  # noqa: ANN001
            super().__init__(turns)
            self.said = said
            self.calls = list(calls)
            self.dropped = False
            self.asked: list[str] = []

        async def create(self, **body: Any):  # noqa: ANN201
            self.asked.append(str(body.get("model")))
            if self.dropped:
                return await super().create(**body)
            self.dropped = True
            said, calls = self.said, self.calls

            class Stream:
                def __aiter__(self):  # noqa: ANN204
                    return self._events()

                async def _events(self):  # noqa: ANN202
                    yield {
                        "event_type": "interaction.created",
                        "interaction": {"id": "int_drop", "status": "in_progress"},
                    }
                    for chunk in said:
                        yield {
                            "event_type": "step.delta",
                            "index": 0,
                            "delta": {"type": "text", "text": chunk},
                        }
                    for index, call in enumerate(calls, start=1):
                        yield {
                            "event_type": "step.start",
                            "index": index,
                            "step": {
                                "type": "function_call",
                                "id": call.id,
                                "name": call.name,
                                "arguments": call.args,
                            },
                        }
                        yield {"event_type": "step.stop", "index": index}
                    yield {
                        "event_type": "error",
                        "error": {"code": "api_error", "message": "high demand"},
                    }

            return Stream()

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

    def test_the_turn_starts_over_on_the_standby_rather_than_dying(self) -> None:
        client = self.Drops(["Let me set"], [(["Here you go."], [])])
        events = self._run(client)

        assert not [e for e in events if e["type"] == "error"], "a blank screen is not an answer"
        assert client.asked == ["gemini-3.8-flash", FALLBACK_MODEL], "finished on the one that was up"
        assert [e for e in events if e["type"] == "restart"], "the client has to drop the half sentence"
        said = [e for e in events if e["type"] == "served_by"]
        assert said and said[0]["model"] == FALLBACK_MODEL, "and be told who answered"

    def test_the_abandoned_half_sentence_is_disowned(self) -> None:
        """`restart` arrives before the replacement prose, or they read as one."""
        client = self.Drops(["Let me set"], [(["Here you go."], [])])
        events = self._run(client)

        order = [e["type"] for e in events]
        restart = order.index("restart")
        after = [
            e["delta"] for e in events[restart:] if e["type"] == "text"
        ]
        assert "".join(after).strip() == "Here you go.", "the second attempt, whole"

    def test_a_turn_that_already_ran_a_tool_is_not_replayed(self) -> None:
        """`save_trip` has already changed the trip; a restart would do it twice."""
        client = self.Drops(
            ["Let me set"],
            [(["Here you go."], [])],
            calls=[ToolCall(id="c1", name="save_trip", args={"destination": "Lisbon"})],
        )
        events = self._run(client)

        assert client.asked == ["gemini-3.8-flash"], "asked once — the tool already ran"
        assert [e for e in events if e["type"] == "error"], "and the failure is reported, not hidden"


def test_a_block_begun_but_never_drawn_does_not_block_the_restart() -> None:
    """The refusal that cost three turns in four.

    `_standby` has to know whether a surface reached the screen. Asked to guess
    from the text, it treated a turn that had *started* writing `<a2ui` as one
    that had drawn — but a stream that drops part-way through a block leaves a
    fragment that never compiled and never painted. Traced against the real
    API, that was three of every four refusals, each one a turn that could have
    finished on the standby and instead ended blank.
    """
    client = TestTheModelDropsTheStreamMidSentence.Drops(
        ["Here you go.\n<a2ui>\nd = Date"],
        [([f"{A2UI_OPEN}\nt = Text(\"Hi\")\nroot = Column([t])\n{A2UI_CLOSE}"], [])],
    )
    events = TestTheModelDropsTheStreamMidSentence._run(
        TestTheModelDropsTheStreamMidSentence(), client
    )

    assert [e for e in events if e["type"] == "restart"], "an unfinished block is not a surface"
    assert client.asked[:2] == ["gemini-3.8-flash", FALLBACK_MODEL], "it went to the standby"
    assert [e for e in events if e["type"] == "ui"], "and the standby finished the job"


def test_a_surface_already_on_screen_still_blocks_the_restart() -> None:
    """The other half of the same rule: a drawn surface is not repeated."""
    client = TestTheModelDropsTheStreamMidSentence.Drops(
        [f"{A2UI_OPEN}\nt = Text(\"Drawn\")\nroot = Column([t])\n{A2UI_CLOSE}\nand then"],
        [(["Here you go."], [])],
    )
    events = TestTheModelDropsTheStreamMidSentence._run(
        TestTheModelDropsTheStreamMidSentence(), client
    )

    assert not [e for e in events if e["type"] == "restart"], "it drew — a rerun would draw twice"
    assert FALLBACK_MODEL not in client.asked, "and the standby was never asked"
    assert [e for e in events if e["type"] == "error"], "the failure is reported instead"
