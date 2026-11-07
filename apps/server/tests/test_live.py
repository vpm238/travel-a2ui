"""A whole voice call, driven off a scripted Live session.

The transport is injected on both sides — the browser's socket is a `send`
coroutine and an async iterator, the Live session is a fake client — so this
runs with no key, no socket and no audio hardware, and the relay does not know
what runtime it is in.

What is worth testing here is what a call does *besides* carrying audio:

  - `ready` means a session exists, not that a frame was written;
  - `render_a2ui_express` draws through the same processor as a typed turn,
    and tells the model what was wrong when a block is refused;
  - a lookup's rows fill a card the model drew, and the model is not handed
    them to read aloud;
  - a tool that changes the trip moves the panel beside the call, as data;
  - the first panel is drawn once, through the Interactions API.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from travel_a2ui.brain import trip as trip_model  # noqa: F401
from travel_a2ui.brain.skills import build_system_prompt
from travel_a2ui.brain.providers.fixture import FixtureProvider
from travel_a2ui.brain.ui import Canvas
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


def interrupted_frame() -> Frame:
    """The traveller spoke over the model, as the API reports it."""
    return Frame(server_content=Obj(model_turn=None, turn_complete=False, interrupted=True))


def turn_complete_frame() -> Frame:
    return Frame(server_content=Obj(model_turn=None, turn_complete=True))


def run_call(
    frames: list[Any],
    *,
    trip: dict[str, Any] | None = None,
    incoming: list[dict[str, Any]] | None = None,
    interactions: list[list[str]] | None = None,
    canvas: Canvas | None = None,
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
        canvas=canvas or Canvas(),
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

    The fake yields each scripted turn once, so a relay that stops after the
    first turn cannot pass by replaying the script.
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

    def test_the_session_opens_on_gemini_3_8_live(self) -> None:
        """The first Live model on a stable channel, and the named successor to
        every preview this pointed at before — each of which was withdrawn and
        answered a connect with NOT_FOUND."""
        import os

        if "VOICE_MODEL" in os.environ:
            pytest.skip("VOICE_MODEL is overridden in this environment")
        _, client, _ = run_call([])
        assert client.model == "gemini-3.8-live"

    def test_the_setup_carries_every_tool_a_call_may_use(self) -> None:
        _, client, _ = run_call([])
        declared = {
            tool["name"] for tool in client.config["tools"][0]["function_declarations"]
        }
        assert {"render_a2ui_express", "search_flights", "save_trip"} <= declared
        assert not any(name.startswith("show_") for name in declared)

    def test_every_tool_is_declared_blocking(self) -> None:
        """Gemini 3.8 Live made asynchronous calls the default: the model fires
        the call, keeps talking, ends its turn, and speaks again whenever the
        result lands. The relay counts turns — one nudge per turn, "did this
        turn call anything", the panel refresh after a call — on the assumption
        that a result arrives inside the turn that asked for it. Left to the
        new default, none of that accounting holds."""
        _, client, _ = run_call([])
        behaviors = {
            tool["name"]: tool.get("behavior")
            for tool in client.config["tools"][0]["function_declarations"]
        }
        assert behaviors and set(behaviors.values()) == {"BLOCKING"}, behaviors

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
        assert config["output_audio_transcription"] == {}

        # And it has to be heard in the language they spoke. Left to detect per
        # utterance, English in an accent it was unsure of came back
        # transliterated — "plan me a trip from San Francisco" rendered as
        # "प्लांट मी अ ट्रिप फ्रॉम सन फ्रांसिस्को", the same sounds in another
        # script. The model understood it, so nothing downstream complained;
        # the traveller just could not read their own sentence back.
        #
        # Naming the language is what turns detection off — the deprecated
        # `language_auto` flag is a nested object rather
        # than the boolean it reads like, so setting it False is rejected by the
        # setup frame and takes the whole session with it.
        assert config["input_audio_transcription"] == {"language_codes": ["en-US"]}
        assert config["speech_config"]["language_code"] == "en-US"

    def test_a_voice_and_a_language_coexist(self) -> None:
        """`speech_config` carries both; setting one never drops the other."""
        config = setup_config("SYSTEM", voice="Puck")
        assert config["speech_config"]["language_code"] == "en-US"
        assert config["speech_config"]["voice_config"] == {
            "prebuilt_voice_config": {"voice_name": "Puck"}
        }

    def test_the_voice_brief_is_appended_and_does_not_replace_the_prompt(self) -> None:
        config = setup_config("THE ORDINARY PROMPT")
        assert "THE ORDINARY PROMPT" in config["system_instruction"]
        # Not the phrasing — the phrasing changed once already, and pinning it
        # is how a test ends up defending the wording it was written beside.
        # What has to be true is that the spoken brief is *there*, and that the
        # rule it exists for survived the edit: a turn with something to show
        # ends with something drawn. The model answering "let me find those for
        # you" and stopping is the failure this whole surface has.
        instruction = config["system_instruction"]
        assert "spoken" in instruction
        assert "Drawing is not optional" in instruction
        assert "phone call" not in instruction, "voice is not a call — see prompts/live.md"


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

    def test_speaking_over_the_answer_reaches_the_browser(self) -> None:
        """The model stops on its own. The browser does not: it queues audio
        ahead of playback, so at the moment somebody says "stop" there can be
        seconds already scheduled — and told nothing, it plays them out."""
        seen, _, _ = run_call([audio_frame("QUJD"), interrupted_frame()])
        kinds = [event["type"] for event in seen]
        assert "interrupted" in kinds
        assert kinds.index("audio") < kinds.index("interrupted")

    def test_a_promise_with_nothing_called_is_handed_back_once(self) -> None:
        """Asked for flights six times, the model said "Let me find some flights
        for you" and ended the turn five of them. The turn is handed back once
        with what it actually did — and the nudge is spent, so a second promise
        in the same turn cannot loop it."""
        seen, client, _ = run_call(
            [
                [
                    transcript_frame("Let me find some flights for you", "agent"),
                    turn_complete_frame(),
                ],
                [
                    transcript_frame("Let me look into that", "agent"),
                    turn_complete_frame(),
                ],
            ]
        )
        nudges = [
            kwargs
            for kind, kwargs in client.live_session.sent
            if kind == "text" and "[system]" in kwargs["turns"]["parts"][0]["text"]
        ]
        assert len(nudges) == 1, "once, and only once"
        # The nudged turn did not end — the browser saw no `turn_end` until the
        # turn that answered the nudge had spoken.
        kinds = [event["type"] for event in seen]
        assert kinds.index("turn_end") > kinds.index("transcript", 1)

    def test_a_cut_off_promise_is_not_nudged(self) -> None:
        """"Let me find some flights" with nothing called is handed back once —
        unless the traveller is the one who ended it. Then prodding the model
        to finish would have it talk over the person who just interrupted it."""
        seen, client, _ = run_call(
            [
                transcript_frame("Let me find some flights for you", "agent"),
                interrupted_frame(),
                turn_complete_frame(),
            ]
        )
        nudges = [
            kwargs
            for kind, kwargs in client.live_session.sent
            if kind == "text" and "[system]" in kwargs["turns"]["parts"][0]["text"]
        ]
        assert nudges == [], "the turn was the traveller's to end"
        assert "turn_end" in [event["type"] for event in seen]


def render_frame(express: str, call_id: str = "r1") -> Frame:
    return tool_frame("render_a2ui_express", {"express": express}, call_id)


def drawn(seen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [message for event in seen if event["type"] == "ui" for message in event["messages"]]


MADRID = {"destination": "Madrid", "origin": "JFK", "startDate": "2027-04-12", "endDate": "2027-04-18", "travelers": 2}


class TestDrawing:
    def test_a_block_is_drawn_through_the_processor(self) -> None:
        seen, client, _ = run_call(
            [render_frame('heading = Text("### Fares")\nfares = Flights()\nroot = Column([heading, fares])')],
            trip=MADRID,
        )
        created = [m["createSurface"] for m in drawn(seen) if "createSurface" in m]
        assert [c["surfaceId"] for c in created] == ["voice-1"]
        # The macro reached the browser expanded.
        components = {c["component"] for c in created[0]["components"]}
        assert "Flights" not in components and "List" in components
        response = client.live_session.tool_responses[0]["function_responses"][0]["response"]
        assert response == {"shown": True, "surfaces": ["voice-1"]}

    def test_a_refused_block_is_explained_to_the_model(self) -> None:
        seen, client, _ = run_call([render_frame('root = Text("hi", nonsense=3)')])
        assert not [m for m in drawn(seen) if "createSurface" in m]
        response = client.live_session.tool_responses[0]["function_responses"][0]["response"]
        assert response["shown"] is False and response["problems"]

    def test_each_block_is_a_new_card(self) -> None:
        seen, _, _ = run_call(
            [render_frame('root = Text("one")', "r1"), render_frame('root = Text("two")', "r2")]
        )
        created = [m["createSurface"]["surfaceId"] for m in drawn(seen) if "createSurface" in m]
        assert created == ["voice-1", "voice-2"]

    def test_a_lookup_fills_the_card_and_is_not_read_out(self) -> None:
        args = {"origin": "JFK", "destination": "Madrid", "date": "2027-04-12", "travelers": 2}
        seen, client, _ = run_call(
            [
                render_frame("fares = Flights()\nroot = Column([fares])"),
                tool_frame("search_flights", args, "s1"),
            ],
            trip=MADRID,
        )
        rows = [
            m["updateDataModel"]
            for m in drawn(seen)
            if "updateDataModel" in m and m["updateDataModel"]["path"] == "/flights"
        ]
        assert rows and rows[0]["surfaceId"] == "voice-1" and rows[0]["value"]
        answered = client.live_session.tool_responses[1]["function_responses"][0]["response"]
        assert isinstance(answered["flights"], str), "the rows are on screen, not in the answer"


class TestThePanel:
    def test_a_trip_with_no_panel_gets_one_after_the_turn(self) -> None:
        panel = ['<a2ui>\nsurface("sidebar")\npanel = Trip("Your trip")\nroot = Column([panel])\n</a2ui>']
        seen, client, _ = run_call(
            [transcript_frame("Madrid it is.", "agent"), turn_complete_frame()],
            trip=MADRID,
            interactions=[panel],
        )
        assert len(client.interaction_bodies) == 1
        assert any(m.get("createSurface", {}).get("surfaceId") == "sidebar" for m in drawn(seen))

    def test_a_panel_already_drawn_moves_by_data_alone(self) -> None:
        canvas = Canvas()
        from travel_a2ui.brain import data
        from travel_a2ui.brain.ui import Drawing

        values = lambda _s: data.session_values(MADRID, None)  # noqa: E731
        Drawing(canvas, "sidebar", values).feed('<a2ui>\nsurface("sidebar")\npanel = Trip()\nroot = Column([panel])\n</a2ui>')
        canvas.provide(values)
        seen, client, saved = run_call(
            [tool_frame("save_trip", {"travelers": 3}), turn_complete_frame()],
            trip=MADRID,
            canvas=canvas,
        )
        assert client.interaction_bodies == [], "no model turn for a panel that exists"
        assert saved["travelers"] == 3
        panel = [
            m["updateDataModel"]
            for m in drawn(seen)
            if "updateDataModel" in m and m["updateDataModel"]["surfaceId"] == "sidebar"
        ]
        assert panel and "3 travelling" in str(panel[-1]["value"])

    def test_nothing_is_drawn_before_there_is_a_trip(self) -> None:
        _, client, _ = run_call([turn_complete_frame()])
        assert client.interaction_bodies == []


class TestAPressDuringACall:
    def test_a_v1_press_is_recorded_and_told(self) -> None:
        press = {
            "type": "press",
            "a2ui": [
                {
                    "version": "1.0",
                    "action": {
                        "name": "select_flight",
                        "surfaceId": "voice-1",
                        "sourceComponentId": "fares_0",
                        "timestamp": "2027-03-01T10:00:00Z",
                        "context": {"id": "IB6250", "price": 412, "airline": "Iberia"},
                        "userMessage": "Chose Iberia",
                    },
                }
            ],
        }
        _, client, saved = run_call([], trip=MADRID, incoming=[press])
        assert saved.get("selectedFlight") == "IB6250"
        told = [k["turns"]["parts"][0]["text"] for kind, k in client.live_session.sent if kind == "text"]
        assert told and "select_flight" in told[0] and "Chose Iberia" in told[0]


class TestFailures:
    def test_a_rejected_key_is_said_in_words(self) -> None:
        class Refusing(FakeClient):
            def connect(self, *, model: str, config: Any):  # noqa: ANN201
                raise RuntimeError("API key not valid. 403")

        seen: list[dict[str, Any]] = []

        async def send(message: dict[str, Any]) -> None:
            seen.append(message)

        async def nothing():  # noqa: ANN202
            if False:
                yield {}

        session = VoiceSession(
            api_key="bad", trip={}, provider=FixtureProvider(), contract="c", client=Refusing([])
        )
        asyncio.run(relay(session, send, nothing()))
        errors = [e["message"] for e in seen if e["type"] == "error"]
        assert errors and "rejected" in errors[0]

    def test_a_call_always_ends_with_turn_end(self) -> None:
        seen, _, _ = run_call([])
        assert seen[-1]["type"] == "turn_end"


def test_the_tool_list_leads_with_the_drawing_tool() -> None:
    assert voice_tools()[0]["name"] == "render_a2ui_express"


class TestStoppingTheMicrophoneIsNotHangingUp:
    def test_a_closed_microphone_lets_the_model_take_its_turn(self) -> None:
        _, client, _ = run_call([], incoming=[{"type": "audio_end"}])
        assert ("audio", {"audio_stream_end": True}) in client.live_session.sent

    def test_leaving_still_ends_it(self) -> None:
        seen, _, _ = run_call([], incoming=[{"type": "end"}])
        assert seen[-1]["type"] == "turn_end"


class TestASpokenTurnDrawsWithATool:
    def test_the_spoken_prompt_teaches_the_tool(self) -> None:
        said = build_system_prompt(surface="inline", surface_id="voice", trip={}, today="2027-03-01", draws="tools")
        assert "render_a2ui_express" in said
        assert "becomes a new card" in said

    def test_and_the_same_express_as_a_typed_turn(self) -> None:
        typed = build_system_prompt(surface="inline", surface_id="inline-1", trip={}, today="2027-03-01")
        spoken = build_system_prompt(surface="inline", surface_id="voice", trip={}, today="2027-03-01", draws="tools")
        from travel_a2ui.brain.catalog import PROCESSOR

        assert PROCESSOR.prompt_snippet in typed and PROCESSOR.prompt_snippet in spoken


class TestNobodyShouldHaveToHearExpressReadAloud:
    """The safety net under the prompt.

    It cannot unsay the audio — by the time a transcript arrives the words are
    already out — but it keeps the written record readable, and it makes the
    mistake legible instead of burying it in a wall of notation.
    """

    def said(self, text: str) -> str:
        from travel_a2ui.doors.live import _without_markup

        return _without_markup(text)

    def test_ordinary_speech_is_left_exactly_as_it_was(self) -> None:
        line = "Four fares up — the Iberia one is cheapest and gets in before lunch."
        assert self.said(line) == line

    def test_a_sentence_about_a_surface_is_not_mistaken_for_one(self) -> None:
        line = "I've put the flights on the screen for you."
        assert self.said(line) == line

    def test_the_block_markers_go(self) -> None:
        assert self.said("<a2ui>") == ""
        assert self.said("</a2ui>") == ""

    def test_express_statements_go(self) -> None:
        assert self.said('surface("voice-1")') == ""
        assert self.said('$/trip/origin = "JFK"') == ""
        assert self.said('f1 = FlightOption("Iberia", "18:40")') == ""

    def test_prose_survives_a_block_beside_it(self) -> None:
        heard = self.said('Here they are.\n<a2ui>\nsurface("voice-1")\n')
        assert heard == "Here they are."


class TestMarkupNeverReachesTheEar:
    """A Live turn's text *is* its speech, so a tag in it gets read aloud.

    The Express spellings were caught; JSX was not, and this went out as the
    agent's own voice: "Let me pull the best JFK to Madrid fares for April,
    less than List variant equals quote divided quote greater than…"
    """

    LEAK = (
        'Let me pull the best JFK to Madrid fares for April.<List variant="divided">\n'
        '  <FlightOption id="IB8158" airline="Iberia" flightNumber="IB650"'
    )

    def test_the_sentence_survives_and_the_markup_does_not(self) -> None:
        from travel_a2ui.doors.live import _without_markup

        said = _without_markup(self.LEAK)
        assert said == "Let me pull the best JFK to Madrid fares for April."
        assert "<" not in said

    def test_express_is_still_caught(self) -> None:
        from travel_a2ui.doors.live import _without_markup

        assert _without_markup("Here you go.\nroot = Column([a])") == "Here you go."
        assert _without_markup("<a2ui>\nroot = Column([a])\n</a2ui>") == ""

    def test_ordinary_speech_is_untouched(self) -> None:
        from travel_a2ui.doors.live import _without_markup

        for line in (
            "Four fares are up; TAP is nonstop and gets in before dinner.",
            "Anything under <500 dollars works.",
            "About four hundred and twenty each.",
        ):
            assert _without_markup(line) == line

