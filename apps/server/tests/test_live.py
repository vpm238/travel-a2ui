"""A whole voice call, driven off a scripted Live session.

The transport is injected on both sides — the browser's socket is a `send`
coroutine and an async iterator, the Live session is a fake client — so this
runs with no key, no socket and no audio hardware. That is not only convenient:
writing the relay around one runtime's WebSocket is where three of the
TypeScript version's bugs came from, and a relay that can be driven by a list is
a relay that does not know what runtime it is in.

What is worth testing here is what a call does *besides* carrying audio:

  - `ready` means a session exists, not that a frame was written;
  - a surface tool draws and hands the model a summary, not the flight list;
  - a tool that changes the trip moves the panel beside the call — the gap the
    Worker never closed, and the one that makes a call feel unheard;
  - a redraw costs one model turn, and only when the decisions changed shape.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from travel_a2ui.brain.providers.fixture import FixtureProvider
from travel_a2ui.doors.live import VoiceSession, relay, setup_config, voice_tools


class FakeLive:
    """A Live session that yields the frames it was given, one turn at a time.

    Faithful to the SDK on the point that mattered: `receive()` is **one turn**,
    not the session — its own loop breaks when the interaction completes, and
    the caller is expected to call it again for the next turn. This fake used to
    re-yield the whole script on every call, which made a relay that iterated
    `receive()` exactly once look correct here and answer exactly one turn in
    production.

    A flat list is one turn, which is what most of these tests want. A list of
    lists is a conversation.
    """

    def __init__(self, frames: list[Any]) -> None:
        self.frames = frames
        self.turns: list[list[Any]] = (
            [list(turn) for turn in frames]
            if frames and all(isinstance(turn, list) for turn in frames)
            else [list(frames)]
        )
        self.received = 0
        self.sent: list[Any] = []
        self.tool_responses: list[Any] = []

    async def __aenter__(self):  # noqa: ANN204
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def send_realtime_input(self, **kwargs: Any) -> None:
        self.sent.append(("audio", kwargs))

    async def send_client_content(self, **kwargs: Any) -> None:
        self.sent.append(("text", kwargs))

    async def send_tool_response(self, **kwargs: Any) -> None:
        self.tool_responses.append(kwargs)

    async def receive(self):  # noqa: ANN201
        """One turn's frames. Exhausted after the last turn, like a closed socket."""
        turn = self.turns[self.received] if self.received < len(self.turns) else []
        self.received += 1
        for frame in turn:
            yield frame


class FakeClient:
    """Shaped like the SDK client, in the two places the relay touches it."""

    def __init__(self, frames: list[Any], interactions: list[list[str]] | None = None) -> None:
        self.live_session = FakeLive(frames)
        self.config: dict[str, Any] | None = None
        self.model: str | None = None
        self.interaction_bodies: list[dict[str, Any]] = []
        self._interactions = list(interactions or [])

    @property
    def aio(self):  # noqa: ANN201
        return self

    @property
    def live(self):  # noqa: ANN201
        return self

    def connect(self, *, model: str, config: Any):  # noqa: ANN201
        self.model = model
        self.config = config
        return self.live_session

    # The panel redraw goes through the Interactions API, not the Live session.
    @property
    def interactions(self):  # noqa: ANN201
        return self

    async def create(self, **body: Any):  # noqa: ANN201
        self.interaction_bodies.append(body)
        chunks = self._interactions.pop(0) if self._interactions else []

        class Stream:
            async def __aiter__(self):  # noqa: ANN204
                yield {
                    "event_type": "interaction.created",
                    "interaction": {"id": "int_panel", "status": "in_progress"},
                }
                for chunk in chunks:
                    yield {
                        "event_type": "step.delta",
                        "index": 0,
                        "delta": {"type": "text", "text": chunk},
                    }
                yield {
                    "event_type": "interaction.completed",
                    "interaction": {"id": "int_panel", "status": "completed"},
                }

        return Stream()


class Frame:
    """One `LiveServerMessage`, in the shape the relay reads."""

    def __init__(self, **fields: Any) -> None:
        self.server_content = fields.get("server_content")
        self.tool_call = fields.get("tool_call")
        self.go_away = fields.get("go_away")
        self.setup_complete = fields.get("setup_complete")


class Obj:
    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


def audio_frame(data: str) -> Frame:
    part = Obj(inline_data=Obj(data=data))
    return Frame(server_content=Obj(model_turn=Obj(parts=[part]), turn_complete=False))


def transcript_frame(text: str, who: str) -> Frame:
    key = "output_transcription" if who == "agent" else "input_transcription"
    return Frame(server_content=Obj(model_turn=None, turn_complete=False, **{key: Obj(text=text)}))


def tool_frame(name: str, args: dict[str, Any], call_id: str = "c1") -> Frame:
    return Frame(tool_call=Obj(function_calls=[Obj(name=name, args=args, id=call_id)]))


def run_call(
    frames: list[Any],
    *,
    trip: dict[str, Any] | None = None,
    incoming: list[dict[str, Any]] | None = None,
    interactions: list[list[str]] | None = None,
) -> tuple[list[dict[str, Any]], FakeClient, dict[str, Any]]:
    """Runs one call and returns what the browser saw."""
    client = FakeClient(frames, interactions)
    seen: list[dict[str, Any]] = []
    saved: dict[str, Any] = {}

    async def send(message: dict[str, Any]) -> None:
        seen.append(message)

    async def messages():  # noqa: ANN202
        for item in incoming or []:
            yield item

    session = VoiceSession(
        api_key="not-a-real-key",
        trip=dict(trip or {}),
        provider=FixtureProvider(),
        contract="stamp-1",
        on_trip=lambda value: saved.update(value),
        client=client,
    )
    asyncio.run(relay(session, send, messages()))
    return seen, client, saved


class TestACallIsMoreThanOneTurn:
    """The bug that made voice look like it ignored people.

    `receive()` is one turn, not the session: the SDK's own loop breaks when the
    interaction completes and the caller is expected to call it again. The relay
    iterated it exactly once, so the first answer arrived, the traveller
    replied, and nothing ever came back — and `_race` then tore the call down
    because a pump had "finished".

    The fake used to re-yield its whole script on every call, which is what let
    this pass for the life of the suite.
    """

    def test_a_second_turn_is_answered(self) -> None:
        seen, _, _ = run_call(
            [
                [transcript_frame("First.", "agent")],
                [transcript_frame("Second.", "agent")],
            ],
            incoming=[{"type": "text", "text": "hello"}, {"type": "text", "text": "and again"}],
        )
        said = [event["text"] for event in seen if event["type"] == "transcript"]
        assert said == ["First.", "Second."], "the call stopped listening after one turn"

    def test_an_exhausted_session_ends_the_call(self) -> None:
        """And does not spin: a turn that yields nothing is a closed socket."""
        seen, _, _ = run_call([[transcript_frame("Only.", "agent")]])
        assert [event["text"] for event in seen if event["type"] == "transcript"] == ["Only."]


class TestOpeningTheSession:
    def test_ready_carries_the_contract_it_was_bound_to(self) -> None:
        """So a stored instantiation can find out the catalog moved."""
        seen, _, _ = run_call([])
        ready = next(event for event in seen if event["type"] == "ready")
        assert ready["contract"] == "stamp-1"
        assert ready["model"].startswith("gemini-")

    def test_the_setup_carries_every_tool_a_call_may_use(self) -> None:
        _, client, _ = run_call([])
        declared = {
            tool["name"] for tool in client.config["tools"][0]["function_declarations"]
        }
        assert {"show_flight_options", "show_hotel_options", "save_trip"} <= declared

    def test_the_schemas_are_cleaned_or_the_whole_setup_is_refused(self) -> None:
        """The Live API rejects the entire setup over one unsupported keyword.

        And says so about the setup, not about the schema — so a session simply
        fails to open with nothing pointing at the cause.
        """
        import json

        config = json.dumps(setup_config("SYSTEM"))
        assert "additionalProperties" not in config
        assert "$schema" not in config
        assert '"strict"' not in config

    def test_both_transcripts_are_on(self) -> None:
        # What they said is the only way to show a caller they were heard.
        config = setup_config("SYSTEM")
        assert config["input_audio_transcription"] == {}
        assert config["output_audio_transcription"] == {}

    def test_the_voice_brief_is_appended_and_does_not_replace_the_prompt(self) -> None:
        config = setup_config("THE ORDINARY PROMPT")
        assert "THE ORDINARY PROMPT" in config["system_instruction"]
        assert "on a phone call" in config["system_instruction"]


class TestCarryingTheCall:
    def test_audio_goes_straight_through(self) -> None:
        seen, _, _ = run_call([audio_frame("QUJD")])
        audio = [event for event in seen if event["type"] == "audio"]
        assert audio and audio[0]["data"] == "QUJD"

    def test_both_sides_of_the_transcript_reach_the_browser(self) -> None:
        seen, _, _ = run_call(
            [transcript_frame("four fares up", "agent"), transcript_frame("madrid", "you")]
        )
        said = {(e["who"], e["text"]) for e in seen if e["type"] == "transcript"}
        assert ("agent", "four fares up") in said
        assert ("you", "madrid") in said

    def test_microphone_bytes_go_upstream(self) -> None:
        _, client, _ = run_call([], incoming=[{"type": "audio", "data": "QUJD"}])
        kinds = [kind for kind, _ in client.live_session.sent]
        assert "audio" in kinds

    def test_typing_during_a_call_still_works(self) -> None:
        _, client, _ = run_call([], incoming=[{"type": "text", "text": "make it three"}])
        sent = dict(client.live_session.sent)["text"]
        assert sent["turns"]["parts"][0]["text"] == "make it three"

    def test_a_closing_session_says_so(self) -> None:
        seen, _, _ = run_call([Frame(go_away=Obj(time_left=None))])
        assert any("closing" in e.get("message", "") for e in seen if e["type"] == "error")


class TestDrawing:
    def test_a_surface_tool_draws_and_the_model_gets_only_a_summary(self) -> None:
        """The whole reason voice and a screen are worth pairing.

        Handing the model the flight list invites it to read the flight list
        out, which is the one thing this mode is for not doing.
        """
        seen, client, _ = run_call(
            [
                tool_frame(
                    "show_flight_options",
                    {"destination": "Madrid", "origin": "JFK", "date": "2099-04-12"},
                )
            ]
        )
        drawn = next(e for e in seen if e["type"] == "ui")
        # One surface per drawing. This asserted `mcp-flights` — the id keyed
        # by *what* was shown rather than *when* — which meant a second flight
        # search in the same call overwrote the first while the traveller was
        # still looking at it.
        assert drawn["surfaceId"] == "voice-1"
        assert any("createSurface" in m for m in drawn["messages"])

        response = client.live_session.tool_responses[0]["function_responses"][0]["response"]
        assert response["shown"] is True
        assert "summary" in response
        # A count and at most one fare — not four airlines and four times.
        assert "FlightOption" not in str(response)

    def test_a_place_nobody_wrote_down_is_drawn_on_a_call_too(self) -> None:
        """The voice agent refused what the typed agent planned.

        It was obeying the prompt's list while the fixture invented fares for
        anything, and "I can't book trips from San Francisco" was the result of
        the two disagreeing. Now both generate, and both label it.
        """
        seen, client, _ = run_call(
            [
                tool_frame(
                    "show_flight_options",
                    {"destination": "Atlantis", "origin": "JFK", "date": "2099-04-12"},
                )
            ]
        )
        response = client.live_session.tool_responses[0]["function_responses"][0]["response"]
        assert response["shown"] is True
        assert [e for e in seen if e["type"] == "ui"], "and it is on screen"

    def test_missing_inputs_are_refused_before_anything_is_looked_up(self) -> None:
        """The order matters: there is no point resolving a city with no date."""
        _, client, _ = run_call([tool_frame("show_flight_options", {"destination": "Madrid"})])
        response = client.live_session.tool_responses[0]["function_responses"][0]["response"]
        assert response["shown"] is False
        assert "$/trip/startDate" in response["error"], "it names what to bind"

    def test_the_surface_goes_through_the_same_passes_as_a_typed_one(self) -> None:
        """So a voice-drawn panel is seeded and bound like any other."""
        seen, _, _ = run_call(
            [tool_frame("show_trip_controls", {"destination": "Madrid"})],
            trip={"destination": "Madrid", "origin": "JFK"},
        )
        drawn = next(e for e in seen if e["type"] == "ui")
        created = next(m for m in drawn["messages"] if "createSurface" in m)
        # `seed_surface_trip` ran: the trip and the plan are in the data model.
        assert created["createSurface"]["dataModel"]["trip"]["origin"] == "JFK"
        assert "plan" in created["createSurface"]["dataModel"]


class TestThePanel:
    """The gap the Worker never closed."""

    def test_a_tool_that_changes_the_trip_moves_the_panel(self) -> None:
        seen, _, saved = run_call(
            [tool_frame("save_trip", {"destination": "Madrid", "travelers": 3})],
            trip={"destination": "Madrid", "travelers": 2},
        )
        # Saying "make it three of us" out loud used to change the trip while
        # the record beside it went on saying two, which reads as the app not
        # having heard — the exact impression the transcripts exist to prevent.
        panels = {
            event["surfaceId"]
            for event in seen
            if event["type"] == "ui" and event["surfaceId"] in ("sidebar", "home")
        }
        assert panels == {"sidebar", "home"}

        trip_event = next(e for e in reversed(seen) if e["type"] == "trip")
        assert trip_event["trip"]["travelers"] == 3
        assert saved["travelers"] == 3, "and the typed conversation sees it too"

    def test_the_panel_rows_arrive_as_data_not_as_a_model_turn(self) -> None:
        seen, client, _ = run_call(
            [tool_frame("save_trip", {"travelers": 3})],
            trip={"destination": "Madrid", "origin": "JFK", "travelers": 2},
        )
        sidebar = next(
            e for e in seen if e["type"] == "ui" and e["surfaceId"] == "sidebar"
        )
        paths = {m["updateDataModel"]["path"] for m in sidebar["messages"]}
        assert "/plan" in paths, "the checklist moves without asking the model"
        assert "/trip/travelers" in paths

    def test_a_changed_shape_redraws_the_panels_through_the_typed_api(self) -> None:
        """One model turn, and not the Live one.

        Asking the Live model for a panel would make it *say* the panel.
        """
        surface = (
            "<a2ui>\nsurface(\"sidebar\")\n"
            'head = Text("Madrid", variant="h3")\nroot = Column([head])\n</a2ui>'
        )
        seen, client, _ = run_call(
            # Selecting a flight is a decision, so the shape moves.
            [tool_frame("save_trip", {"selectedFlight": "IB614"})],
            trip={"destination": "Madrid", "origin": "JFK"},
            interactions=[[surface], [surface]],
        )
        assert len(client.interaction_bodies) == 2, "the sidebar and the home screen"
        assert "Redraw this surface" in client.interaction_bodies[0]["input"][0]["content"][0]["text"]

    def test_an_unchanged_shape_costs_no_model_turn(self) -> None:
        _, client, _ = run_call(
            # A note is not a decision, so nothing needs different controls.
            [tool_frame("save_trip", {"neighborhood": "Lavapiés"})],
            trip={"destination": "Madrid", "origin": "JFK"},
        )
        assert client.interaction_bodies == []

    def test_nothing_is_redrawn_before_there_is_a_trip(self) -> None:
        _, client, _ = run_call([tool_frame("save_trip", {"travelers": 2})], trip={})
        assert client.interaction_bodies == [], "a panel saying 'no trip' is a panel nobody wants"


class TestFailures:
    def test_a_rejected_key_is_said_in_words(self) -> None:
        class Broken(FakeClient):
            def connect(self, *, model: str, config: Any):  # noqa: ANN201
                raise RuntimeError("API key not valid (401)")

        client = Broken([])
        seen: list[dict[str, Any]] = []

        async def send(message: dict[str, Any]) -> None:
            seen.append(message)

        async def messages():  # noqa: ANN202
            return
            yield  # pragma: no cover

        session = VoiceSession(
            api_key="bad", trip={}, provider=FixtureProvider(), contract="s", client=client
        )
        asyncio.run(relay(session, send, messages()))

        error = next(e for e in seen if e["type"] == "error")
        assert "rejected" in error["message"]
        assert "401" not in error["message"], "a status code is not a message"

    def test_a_call_always_ends_with_turn_end(self) -> None:
        """So the client releases the microphone however the call finished."""
        seen, _, _ = run_call([])
        assert seen[-1]["type"] == "turn_end"


def test_the_tool_list_leads_with_the_surface_tools() -> None:
    """It should mostly be drawing; the data tools are there for the rest."""
    names = [tool["name"] for tool in voice_tools()]
    shows = [index for index, name in enumerate(names) if name.startswith("show_")]
    assert shows == list(range(len(shows))), "the show_* tools come first"


class TestACallIsAConversationNotOneCard:
    """Two searches in a call are two surfaces.

    Voice had the bug the typed path had, under a different name: surfaces were
    keyed by what they showed, so every flight search wrote to `mcp-flights`.
    "Flights to Madrid", then "what about Lisbon", and the second replaced the
    first — on a *call*, where the screen is the only record of what was said,
    and the traveller cannot scroll back to the answer they just heard.
    """

    def test_each_drawing_gets_its_own_surface(self) -> None:
        seen, _, _ = run_call(
            [
                tool_frame(
                    "show_flight_options",
                    {"destination": "Madrid", "origin": "JFK", "date": "2099-04-12"},
                ),
                tool_frame(
                    "show_flight_options",
                    {"destination": "Lisbon", "origin": "JFK", "date": "2099-04-12"},
                ),
            ]
        )
        drawn = [event["surfaceId"] for event in seen if event["type"] == "ui"]
        inline = [surface for surface in drawn if surface.startswith("voice-")]
        assert len(inline) == 2, drawn
        assert len(set(inline)) == 2, f"the second search overwrote the first: {inline}"

    def test_the_model_may_still_redraw_one_on_purpose(self) -> None:
        """Naming a surface is how you *mean* to replace it."""
        seen, _, _ = run_call(
            [
                tool_frame(
                    "show_flight_options",
                    {
                        "destination": "Madrid",
                        "origin": "JFK",
                        "date": "2099-04-12",
                        "surfaceId": "voice-keep",
                    },
                )
            ]
        )
        drawn = next(event for event in seen if event["type"] == "ui")
        assert drawn["surfaceId"] == "voice-keep"
