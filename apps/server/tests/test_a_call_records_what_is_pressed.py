"""A voice call keeps the panel current, and says each answer once.

Three things a call has to get right about presses:

  - A press is recorded by the host onto the hop it belongs to, before the
    model hears of it, rather than waiting on the model to call `save_trip`.
  - The panel beside the call moves as data: `Trip()` binds `/panel`, so a
    chosen fare reaches it with no redraw and no model call.
  - A press or typed line sent into a turn still in progress waits for that
    turn, so nothing is answered twice.
"""

from __future__ import annotations

import asyncio
from typing import Any

from test_live import FakeClient, transcript_frame, turn_complete_frame  # noqa: E402

from travel_a2ui.brain import data
from travel_a2ui.brain.providers.fixture import FixtureProvider
from travel_a2ui.brain.ui import Canvas, Drawing
from travel_a2ui.doors.live import VoiceSession, relay

TRIP = {
    "origin": "JFK",
    "destination": "Madrid",
    "startDate": "2027-04-12",
    "endDate": "2027-04-19",
    "travelers": 2,
    "legs": [{"origin": "MAD", "destination": "JFK", "startDate": "2027-04-19"}],
}


def press(surface: str, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "press",
        "a2ui": [
            {
                "version": "1.0",
                "action": {
                    "name": "select_flight",
                    "surfaceId": surface,
                    "sourceComponentId": "fares_0",
                    "timestamp": "2027-03-01T10:00:00Z",
                    "context": context,
                },
            }
        ],
    }


OUTBOUND = press(
    "voice-1",
    {
        "id": "TP2077",
        "price": "€292",
        "from": "JFK",
        "to": "MAD",
        "airline": "TAP Air Portugal",
        "flightNumber": "TP787",
        "departTime": "11:00",
        "arriveTime": "21:44",
    },
)

RETURN = press(
    "voice-2",
    {
        "id": "AF3760",
        "price": "€316",
        "from": "MAD",
        "to": "JFK",
        "airline": "Air France",
        "flightNumber": "AF242",
        "departTime": "14:46",
        "arriveTime": "01:00 +1",
    },
)


def with_panel() -> Canvas:
    """A canvas whose renderer already holds the agent's `Trip()` panel."""
    canvas = Canvas()
    values = lambda _s: data.session_values(TRIP, None)  # noqa: E731
    Drawing(canvas, "sidebar", values).feed(
        '<a2ui>\nsurface("sidebar")\npanel = Trip("Your trip to Madrid")\nroot = Column([panel])\n</a2ui>'
    )
    canvas.provide(values)
    return canvas


def call(
    incoming: list[dict[str, Any]],
    frames: list[Any] | None = None,
    *,
    canvas: Canvas | None = None,
    client: FakeClient | None = None,
    linger: float = 0.0,
) -> tuple[list[dict[str, Any]], FakeClient, dict[str, Any]]:
    client = client or FakeClient(frames or [])
    seen: list[dict[str, Any]] = []
    saved: dict[str, Any] = {}

    async def send(message: dict[str, Any]) -> None:
        seen.append(message)

    async def messages():  # noqa: ANN202
        for item in incoming:
            yield item
        # Held open, as a real socket is, so work after the last message lands.
        await asyncio.sleep(linger)

    session = VoiceSession(
        api_key="not-a-real-key",
        trip={**TRIP, "legs": [dict(leg) for leg in TRIP["legs"]]},
        provider=FixtureProvider(),
        contract="stamp-1",
        on_trip=lambda value: saved.update(value),
        canvas=canvas if canvas is not None else with_panel(),
        client=client,
    )
    asyncio.run(relay(session, send, messages()))
    return seen, client, saved


def told(client: FakeClient) -> list[str]:
    return [kwargs["turns"]["parts"][0]["text"] for kind, kwargs in client.live_session.sent if kind == "text"]


class TestAPressIsRecordedByTheHost:
    def test_the_outbound_lands_on_the_trip(self) -> None:
        _, _, saved = call([OUTBOUND])
        assert saved["airline"] == "TAP Air Portugal"
        assert saved["flightNumber"] == "TP787"
        assert saved["selectedFlight"] == "TP2077"

    def test_the_return_lands_on_its_leg_without_a_hop(self) -> None:
        _, _, saved = call([RETURN])
        assert saved["legs"][0]["airline"] == "Air France"
        assert saved.get("airline") != "Air France", "the return landed on the outbound"

    def test_and_the_model_is_told_what_was_chosen(self) -> None:
        _, client, _ = call([RETURN])
        said = told(client)
        assert len(said) == 1
        assert "select_flight" in said[0] and "legs[0]" in said[0]


class TestThePanelMovesAsData:
    def test_a_chosen_fare_reaches_the_panel(self) -> None:
        seen, client, _ = call([OUTBOUND])
        panel = [
            message["updateDataModel"]
            for event in seen
            if event["type"] == "ui" and event["surfaceId"] == "sidebar"
            for message in event["messages"]
            if "updateDataModel" in message and message["updateDataModel"]["path"] == "/panel"
        ]
        assert panel and "TP787" in str(panel[-1]["value"])
        assert client.interaction_bodies == [], "no model call for a panel that exists"

    def test_the_trip_reaches_the_browser(self) -> None:
        seen, _, _ = call([OUTBOUND])
        trips = [event["trip"] for event in seen if event["type"] == "trip"]
        assert trips and trips[-1]["airline"] == "TAP Air Portugal"


class TestOneAnswerPerThingSaid:
    def test_a_setup_frame_is_not_a_turn(self) -> None:
        """The session's own frames come before anything is said. They must not
        hold the traveller's first message back as if the model were talking."""
        from test_live import Frame

        setup = Frame(setup_complete=True)
        _, client, _ = call([{"type": "text", "text": "first"}], [[setup], []], canvas=Canvas())
        assert told(client) == ["first"]

    def test_a_message_sent_mid_turn_waits_for_the_turn_to_end(self) -> None:
        _, client, _ = call(
            [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}],
            [[transcript_frame("Answering the first.", "agent")]],
        )
        assert told(client) == ["first"], "the second went into a turn still in progress"

    def test_and_then_goes_in_order(self) -> None:
        _, client, _ = call(
            [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}],
            [[transcript_frame("Answering the first.", "agent"), turn_complete_frame()], []],
        )
        assert told(client) == ["first", "second"]


class TestTheFirstPanelIsDrawnOnce:
    def test_one_model_draw_and_never_two_at_once(self) -> None:
        block = ['<a2ui>surface("sidebar")\nrows = Trip("Your trip")\nroot = Column([rows])</a2ui>']

        class SlowClient(FakeClient):
            active = 0
            most = 0

            async def create(self, **body: Any):  # noqa: ANN201
                SlowClient.active += 1
                SlowClient.most = max(SlowClient.most, SlowClient.active)
                await asyncio.sleep(0.05)
                SlowClient.active -= 1
                return await super().create(**body)

        client = SlowClient([[turn_complete_frame()], [turn_complete_frame()]], interactions=[block, block])
        call([OUTBOUND, {"type": "text", "text": "and then"}], canvas=Canvas(), client=client, linger=0.5)
        assert SlowClient.most == 1, "two panel draws ran at once"
        assert len(client.interaction_bodies) == 1, "a panel that exists is not drawn again"
