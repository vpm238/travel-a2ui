"""A voice call keeps the panel current, and says each answer once.

Reported as "the voice mode still does not update the right side bar" and "voice
mode repeats everything twice, sometimes thrice". Reproduced in a real browser
against the real Live model (`tools/e2e/live.mjs`), and three faults:

  - A press during a call reached the model only as a sentence. Nothing was
    recorded unless the model chose to call `save_trip`, and it sometimes said
    "I've recorded that flight" and called nothing.
  - When the trip did change, the panel got data and no redraw. Its rows are
    conditional, so a chosen fare needs components, and the voice door never
    kept the agent's panel composition to replay — the typed door's cheap path.
  - A press or typed line sent into a Live turn still in progress was answered
    twice: once as that turn carried on, once as its own.
"""

from __future__ import annotations

import asyncio
from typing import Any

from travel_a2ui.brain.providers.fixture import FixtureProvider
from travel_a2ui.doors.live import VoiceSession, relay

from test_live import FakeClient, transcript_frame, turn_complete_frame  # noqa: E402

TRIP = {
    "origin": "JFK",
    "destination": "Madrid",
    "startDate": "2027-04-12",
    "endDate": "2027-04-19",
    "travelers": 2,
    "legs": [{"origin": "MAD", "destination": "JFK", "startDate": "2027-04-19"}],
}

OUTBOUND = {
    "name": "select_flight",
    "surfaceId": "voice-1",
    "context": {
        "id": "TP2077",
        "price": "€292",
        "from": "JFK",
        "to": "MAD",
        "airline": "TAP Air Portugal",
        "flightNumber": "TP787",
        "departTime": "11:00",
        "arriveTime": "21:44",
    },
}

RETURN = {
    "name": "select_flight",
    "surfaceId": "voice-2",
    "context": {
        "id": "AF3760",
        "price": "€316",
        "from": "MAD",
        "to": "JFK",
        "airline": "Air France",
        "flightNumber": "AF242",
        "departTime": "14:46",
        "arriveTime": "01:00 +1",
    },
}

#: How the agent composed the panel, as the session keeps it.
PANEL = {"sidebar": 'surface("sidebar")\nrows = Trip("Your trip to Madrid")\nroot = Column([rows])'}


def call(
    incoming: list[dict[str, Any]],
    frames: list[Any] | None = None,
    *,
    panels: dict[str, str] | None = None,
    shape: str | None = "drawn-before",
) -> tuple[list[dict[str, Any]], FakeClient, dict[str, Any], dict[str, str]]:
    client = FakeClient(frames or [])
    seen: list[dict[str, Any]] = []
    saved: dict[str, Any] = {}
    learned: dict[str, str] = {}

    async def send(message: dict[str, Any]) -> None:
        seen.append(message)

    async def messages():  # noqa: ANN202
        for item in incoming:
            yield item

    session = VoiceSession(
        api_key="not-a-real-key",
        trip={**TRIP, "legs": [dict(leg) for leg in TRIP["legs"]]},
        provider=FixtureProvider(),
        contract="stamp-1",
        on_trip=lambda value: saved.update(value),
        shape=shape,
        panels=dict(panels or {}),
        on_panels=lambda value: learned.update(value),
        client=client,
    )
    asyncio.run(relay(session, send, messages()))
    return seen, client, saved, learned


def told(client: FakeClient) -> list[str]:
    return [
        kwargs["turns"]["parts"][0]["text"]
        for kind, kwargs in client.live_session.sent
        if kind == "text"
    ]


class TestAPressIsRecordedByTheHost:
    def test_the_outbound_lands_on_the_trip(self) -> None:
        _, _, saved, _ = call([{"type": "press", "action": OUTBOUND}], panels=PANEL)
        assert saved["airline"] == "TAP Air Portugal"
        assert saved["flightNumber"] == "TP787"
        assert saved["selectedFlight"] == "TP2077"

    def test_the_return_lands_on_its_leg_without_a_hop(self) -> None:
        _, _, saved, _ = call([{"type": "press", "action": RETURN}], panels=PANEL)
        assert saved["legs"][0]["airline"] == "Air France"
        assert saved.get("airline") != "Air France", "the return landed on the outbound"

    def test_and_the_model_is_told_what_was_chosen(self) -> None:
        _, client, _, _ = call([{"type": "press", "action": RETURN}], panels=PANEL)
        said = told(client)
        assert len(said) == 1
        assert "select_flight" in said[0] and "legs[0]" in said[0]


class TestThePanelIsRedrawnFromTheAgentsComposition:
    def test_a_chosen_fare_redraws_the_panel_with_its_row(self) -> None:
        seen, client, _, _ = call([{"type": "press", "action": OUTBOUND}], panels=PANEL)
        drawn = [
            node["component"]
            for event in seen
            if event["type"] == "ui" and event["surfaceId"] == "sidebar"
            for message in event["messages"]
            for key in ("createSurface", "updateComponents")
            for node in (message.get(key) or {}).get("components", [])
        ]
        assert "FlightOption" in drawn, "the panel got data and no row to show it in"
        assert client.interaction_bodies == [], "a replay costs no model call"

    def test_the_trip_reaches_the_browser(self) -> None:
        seen, _, _, _ = call([{"type": "press", "action": OUTBOUND}], panels=PANEL)
        trips = [event["trip"] for event in seen if event["type"] == "trip"]
        assert trips and trips[-1]["airline"] == "TAP Air Portugal"

    def test_a_trip_panel_drawn_in_the_call_is_kept_to_replay(self) -> None:
        from test_live import tool_frame

        _, _, _, learned = call(
            [],
            [[tool_frame("save_trip", {"draw": {"macro": "Trip", "heading": "Madrid"}, "travelers": 2})]],
            shape=None,
        )
        assert "Trip(" in learned.get("sidebar", ""), "the composition was not kept"


class TestOneAnswerPerThingSaid:
    def test_a_message_sent_mid_turn_waits_for_the_turn_to_end(self) -> None:
        _, client, _, _ = call(
            [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}],
            [[transcript_frame("Answering the first.", "agent")]],
        )
        assert told(client) == ["first"], "the second went into a turn still in progress"

    def test_and_then_goes_in_order(self) -> None:
        _, client, _, _ = call(
            [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}],
            [[transcript_frame("Answering the first.", "agent"), turn_complete_frame()], []],
        )
        assert told(client) == ["first", "second"]


class TestTwoChangesAtOnceDrawThePanelOnce:
    """A press landing while the turn's panel is still being drawn.

    The model draw takes seconds, and a fare tapped meanwhile started a second
    draw beside it. The older one — drawn from the trip before the press — could
    land last and put "Nothing settled yet" back next to a chosen flight. Now
    they take turns, and the second change replays the composition the first
    one drew.
    """

    def test_one_model_draw_and_never_two_at_once(self) -> None:
        from test_live import tool_frame

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

        client = SlowClient([[tool_frame("save_trip", {"travelers": 3})]], interactions=[block, block])
        seen: list[dict[str, Any]] = []

        async def send(message: dict[str, Any]) -> None:
            seen.append(message)

        async def messages():  # noqa: ANN202
            yield {"type": "press", "action": OUTBOUND}

        session = VoiceSession(
            api_key="not-a-real-key",
            trip={**TRIP, "legs": [dict(leg) for leg in TRIP["legs"]]},
            provider=FixtureProvider(),
            contract="stamp-1",
            client=client,
        )
        asyncio.run(relay(session, send, messages()))

        assert SlowClient.most == 1, "two panel draws ran at once"
        assert len(client.interaction_bodies) == 1, "the second change should replay, not draw again"
