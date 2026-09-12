"""The HTTP surface, which is mostly about what it refuses and what it advertises.

Two things here are worth real tests. The first is `/api/meta`, because every
client configures itself from it: a field that quietly disappears does not break
this server, it breaks the front end, on a deploy, with no error anywhere near
the change that caused it.

The second is the SSE stream, because its failure mode is silence. A turn that
buffers instead of streaming still returns every event and still renders the
right answer — just all at once, at the end, which is the thing the whole design
is built to avoid.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from travel_a2ui import main


@pytest.fixture()
def client() -> TestClient:
    return TestClient(main.app)


class TestWhatTheClientsConfigureThemselvesFrom:
    def test_meta_carries_everything_a_client_needs(self, client: TestClient) -> None:
        body = client.get("/api/meta").json()
        # Named individually rather than snapshotted: a snapshot of this would
        # be updated without thought the first time it failed, and the point is
        # that removing one of these is a decision.
        for key in (
            "name",
            "catalogId",
            "protocolVersion",
            "defaultModel",
            "defaultSkill",
            "models",
            "surfaces",
            "skills",
            "destinations",
            "provenance",
            "contract",
            "mcpEndpoint",
            "keyProvided",
            "backends",
        ):
            assert key in body, f"clients read {key} out of /api/meta"

    def test_it_says_where_the_data_came_from(self, client: TestClient) -> None:
        """So the chrome can say it once instead of every surface carrying a badge."""
        provenance = client.get("/api/meta").json()["provenance"]
        assert provenance["live"] is False
        assert provenance["label"]
        assert "not real" in provenance["detail"]

    def test_the_catalog_id_is_what_the_wire_will_actually_carry(
        self, client: TestClient
    ) -> None:
        """The model is told this, and `createSurface` carries it. They must match.

        Read from `$id` because that is what the SDK's compiler puts on the
        wire. The catalog's other name for itself, `catalogId`, is the same
        string today; reading the one the compiler uses is what keeps them
        matching if that ever stops being true.
        """
        from travel_a2ui.agent import CATALOG_JSON

        assert client.get("/api/meta").json()["catalogId"] == CATALOG_JSON["$id"]

    def test_both_frameworks_are_offered_and_only_one_has_a_microphone(
        self, client: TestClient
    ) -> None:
        backends = client.get("/api/meta").json()["backends"]
        assert [backend["voice"] for backend in backends] == [False, True]

    def test_the_catalog_is_served_whole(self, client: TestClient) -> None:
        body = client.get("/api/catalog").json()
        assert len(body["components"]) > 20


class TestRefusals:
    def test_a_session_lookup_needs_a_session(self, client: TestClient) -> None:
        assert client.get("/api/session").status_code == 400

    def test_a_reset_needs_a_session(self, client: TestClient) -> None:
        assert client.post("/api/session/reset", json={}).status_code == 400

    def test_a_turn_without_a_key_says_so(self, client: TestClient) -> None:
        response = client.post("/api/chat", json={"message": "hi"})
        assert response.status_code == 401
        # And says what to do about it, because the key comes from the person
        # sitting in front of the app.
        assert "x-goog-api-key" in response.json()["detail"]

    def test_a_malformed_body_is_a_refusal_not_a_crash(self, client: TestClient) -> None:
        response = client.post(
            "/api/chat", content=b"{not json", headers={"content-type": "application/json"}
        )
        assert response.status_code == 401, "the missing key is reported, not a parse error"

    def test_an_unknown_api_route_stays_a_404(self, client: TestClient) -> None:
        """Not the single-page app's index.

        With a built client mounted, an unknown path falls back to `index.html`
        so the app can route it. An API path must not: a typo in a fetch would
        then quietly receive HTML and fail somewhere much less obvious.
        """
        assert client.get("/api/nope").status_code == 404


class TestTheSession:
    def test_a_conversation_comes_back(self, client: TestClient) -> None:
        main.sessions.save("t1", trip={"destination": "Madrid"})
        body = client.get("/api/session", params={"sessionId": "t1"}).json()
        assert body["trip"] == {"destination": "Madrid"}
        assert body["turns"] == 1

    def test_a_reset_forgets_it(self, client: TestClient) -> None:
        main.sessions.save("t2", trip={"destination": "Madrid"})
        client.post("/api/session/reset", json={"sessionId": "t2"})
        assert client.get("/api/session", params={"sessionId": "t2"}).json()["trip"] == {}


class TestTheStream:
    """The SSE turn, with the agent replaced by a scripted one."""

    @staticmethod
    def _events(response: Any) -> list[dict[str, Any]]:
        out = []
        for line in response.text.splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
        return out

    def test_the_session_id_comes_first(self, client: TestClient, monkeypatch) -> None:
        """So a client that did not send one knows what to send next time."""

        async def fake_turn(request):  # noqa: ANN001, ANN202
            yield {"type": "done", "stopReason": "completed"}

        monkeypatch.setattr(main, "run_turn", fake_turn)
        response = client.post(
            "/api/chat", json={"message": "hi"}, headers={"x-goog-api-key": "k"}
        )
        events = self._events(response)
        assert events[0]["type"] == "session"
        assert events[0]["sessionId"]

    def test_every_agent_event_reaches_the_wire(self, client: TestClient, monkeypatch) -> None:
        async def fake_turn(request):  # noqa: ANN001, ANN202
            yield {"type": "text", "delta": "Hello", "round": 0}
            yield {"type": "ui", "surfaceId": "inline-1", "messages": [], "done": True}
            yield {"type": "done", "stopReason": "completed"}

        monkeypatch.setattr(main, "run_turn", fake_turn)
        response = client.post(
            "/api/chat", json={"message": "hi"}, headers={"x-goog-api-key": "k"}
        )
        kinds = [event["type"] for event in self._events(response)]
        assert kinds == ["session", "text", "ui", "done"]

    def test_the_internal_result_event_does_not_reach_the_client(
        self, client: TestClient, monkeypatch
    ) -> None:
        """It carries the trip object the server keeps, not a wire message."""
        from travel_a2ui.agent import TurnResult

        async def fake_turn(request):  # noqa: ANN001, ANN202
            yield {"type": "done", "stopReason": "completed"}
            yield {
                "type": "__result__",
                "result": TurnResult(
                    interaction_id="int_7",
                    trip={"destination": "Lisbon"},
                    stop_reason="completed",
                    shape="shape-1",
                ),
            }

        monkeypatch.setattr(main, "run_turn", fake_turn)
        response = client.post(
            "/api/chat",
            json={"message": "hi", "sessionId": "streamed"},
            headers={"x-goog-api-key": "k"},
        )
        kinds = [event["type"] for event in self._events(response)]
        assert "__result__" not in kinds

        # And it was used: the turn is what updates the session.
        session = main.sessions.get("streamed")
        assert session.interaction_id == "int_7"
        assert session.trip == {"destination": "Lisbon"}
        assert session.shape == "shape-1"

    def test_the_continuation_goes_to_the_client(
        self, client: TestClient, monkeypatch
    ) -> None:
        """The receipt: where the conversation is, and what has been decided."""
        from travel_a2ui.agent import TurnResult

        async def fake_turn(request):  # noqa: ANN001, ANN202
            yield {"type": "done", "stopReason": "completed"}
            yield {
                "type": "__result__",
                "result": TurnResult(
                    interaction_id="int_9",
                    trip={"destination": "Lisbon"},
                    stop_reason="completed",
                    shape="shape-2",
                ),
            }

        monkeypatch.setattr(main, "run_turn", fake_turn)
        response = client.post(
            "/api/chat", json={"message": "hi"}, headers={"x-goog-api-key": "k"}
        )
        resume = [e for e in self._events(response) if e["type"] == "resume"]
        assert len(resume) == 1
        assert resume[0]["interactionId"] == "int_9"
        assert resume[0]["trip"] == {"destination": "Lisbon"}
        assert resume[0]["shape"] == "shape-2"

    def test_another_instance_answers_from_the_receipt(
        self, client: TestClient, monkeypatch
    ) -> None:
        """The case this exists for, and the one nothing else covers.

        Cloud Run does not promise the next turn lands on the instance that
        answered the last one. An instance that has never heard of this session
        finds nothing in memory — and used to start a brand-new Gemini
        conversation with an empty trip, mid-sentence, with the half-planned
        trip still on screen.

        The client is the only party present for every turn, so the client
        carries the thread. `sessionId` here is deliberately one this process
        has never seen: that *is* the second instance.
        """
        seen: dict[str, Any] = {}

        async def fake_turn(request):  # noqa: ANN001, ANN202
            seen["interaction"] = request.interaction_id
            seen["trip"] = request.trip
            seen["shape"] = request.shape
            yield {"type": "done", "stopReason": "completed"}

        monkeypatch.setattr(main, "run_turn", fake_turn)
        client.post(
            "/api/chat",
            json={
                "message": "and a hotel",
                "sessionId": "never-seen-here",
                "resume": {
                    "interactionId": "int_11",
                    "trip": {"destination": "Lisbon"},
                    "shape": "shape-3",
                },
            },
            headers={"x-goog-api-key": "k"},
        )
        assert seen["interaction"] == "int_11"
        assert seen["trip"] == {"destination": "Lisbon"}
        assert seen["shape"] == "shape-3"

    def test_a_junk_receipt_falls_back_rather_than_fails(
        self, client: TestClient, monkeypatch
    ) -> None:
        """It is untrusted input: a client that garbles it gets this instance's
        own memory, not a 500."""
        seen: dict[str, Any] = {}

        async def fake_turn(request):  # noqa: ANN001, ANN202
            seen["interaction"] = request.interaction_id
            seen["trip"] = request.trip
            yield {"type": "done", "stopReason": "completed"}

        monkeypatch.setattr(main, "run_turn", fake_turn)
        main.sessions.save("garbled", interaction_id="int_mine", trip={"destination": "Oslo"})
        client.post(
            "/api/chat",
            json={
                "message": "hi",
                "sessionId": "garbled",
                "resume": {"interactionId": 7, "trip": "Lisbon", "shape": []},
            },
            headers={"x-goog-api-key": "k"},
        )
        assert seen["interaction"] == "int_mine"
        assert seen["trip"] == {"destination": "Oslo"}

    def test_the_stream_is_not_buffered_by_a_proxy(
        self, client: TestClient, monkeypatch
    ) -> None:
        """The header that stops a reverse proxy turning a stream into a wait.

        Cheap to assert and impossible to notice missing: everything works, the
        answer is correct, and it simply all arrives at the end — which is the
        exact experience the streaming exists to replace.
        """

        async def fake_turn(request):  # noqa: ANN001, ANN202
            yield {"type": "done", "stopReason": "completed"}

        monkeypatch.setattr(main, "run_turn", fake_turn)
        response = client.post(
            "/api/chat", json={"message": "hi"}, headers={"x-goog-api-key": "k"}
        )
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        assert response.headers["cache-control"] == "no-store"

    def test_a_key_on_the_request_is_used_and_not_stored(
        self, client: TestClient, monkeypatch
    ) -> None:
        seen: dict[str, Any] = {}

        async def fake_turn(request):  # noqa: ANN001, ANN202
            seen["key"] = request.api_key
            yield {"type": "done", "stopReason": "completed"}

        monkeypatch.setattr(main, "run_turn", fake_turn)
        client.post("/api/chat", json={"message": "hi"}, headers={"x-goog-api-key": "the-key"})
        assert seen["key"] == "the-key"

        # It arrived with the request and left with it: nothing about the
        # session mentions it.
        assert "the-key" not in json.dumps(
            [session.as_dict() for session in main.sessions._sessions.values()]
        )

    def test_an_action_is_read_as_an_action(self, client: TestClient, monkeypatch) -> None:
        seen: dict[str, Any] = {}

        async def fake_turn(request):  # noqa: ANN001, ANN202
            seen["action"] = request.action
            yield {"type": "done", "stopReason": "completed"}

        monkeypatch.setattr(main, "run_turn", fake_turn)
        client.post(
            "/api/chat",
            json={
                "action": {
                    "name": "select_flight",
                    "surfaceId": "inline-1",
                    "context": {"id": "IB614"},
                    "dataModel": {"trip": {"origin": "JFK"}},
                }
            },
            headers={"x-goog-api-key": "k"},
        )
        action = seen["action"]
        assert action is not None
        assert action.name == "select_flight"
        assert action.context == {"id": "IB614"}
        assert action.data_model == {"trip": {"origin": "JFK"}}

    def test_an_unknown_skill_falls_back_rather_than_failing(
        self, client: TestClient, monkeypatch
    ) -> None:
        seen: dict[str, Any] = {}

        async def fake_turn(request):  # noqa: ANN001, ANN202
            seen["skill"] = request.skill
            yield {"type": "done", "stopReason": "completed"}

        monkeypatch.setattr(main, "run_turn", fake_turn)
        client.post(
            "/api/chat",
            json={"message": "hi", "skill": "not-a-skill"},
            headers={"x-goog-api-key": "k"},
        )
        from travel_a2ui.skills import SKILL_VARIANTS

        assert seen["skill"] in SKILL_VARIANTS

def test_health_answers_before_traffic_arrives(client: TestClient) -> None:
    assert client.get("/healthz").json()["ok"] is True


class TestTheVoiceSocket:
    """The handshake, which is where a call fails before anyone speaks."""

    def test_it_refuses_a_frame_that_is_not_a_start(self, client: TestClient) -> None:
        with client.websocket_connect("/api/voice") as socket:
            socket.send_json({"type": "audio", "data": "QUJD"})
            reply = socket.receive_json()
            assert reply["type"] == "error"
            assert "start" in reply["message"]

    def test_it_refuses_a_call_with_no_key(self, client: TestClient) -> None:
        with client.websocket_connect("/api/voice") as socket:
            socket.send_json({"type": "start"})
            reply = socket.receive_json()
            assert reply["type"] == "error"
            assert "API key" in reply["message"]

    def test_a_call_reads_the_trip_the_typed_conversation_holds(
        self, client: TestClient, monkeypatch
    ) -> None:
        """One store. Saying something out loud moves the panel beside it."""
        seen: dict[str, Any] = {}

        async def fake_relay(session, send, incoming):  # noqa: ANN001, ANN202
            seen["trip"] = dict(session.trip)
            seen["contract"] = session.contract
            await send({"type": "ready", "model": "m", "contract": session.contract})
            session.on_trip({"travelers": 3})

        monkeypatch.setattr(main, "relay", fake_relay)
        main.sessions.save("voice-1", trip={"destination": "Madrid", "travelers": 2})

        with client.websocket_connect("/api/voice") as socket:
            socket.send_json({"type": "start", "apiKey": "k", "sessionId": "voice-1"})
            assert socket.receive_json()["type"] == "ready"

        assert seen["trip"]["destination"] == "Madrid"
        assert seen["contract"], "a call is bound to a contract it can be checked against"
        # And what the call changed is what the typed side reads back.
        assert main.sessions.get("voice-1").trip["travelers"] == 3

    def test_the_key_arrives_in_the_opening_frame_and_is_not_stored(
        self, client: TestClient, monkeypatch
    ) -> None:
        seen: dict[str, Any] = {}

        async def fake_relay(session, send, incoming):  # noqa: ANN001, ANN202
            seen["key"] = session.api_key
            await send({"type": "ready", "model": "m", "contract": "c"})

        monkeypatch.setattr(main, "relay", fake_relay)
        with client.websocket_connect("/api/voice") as socket:
            socket.send_json({"type": "start", "apiKey": "the-voice-key", "sessionId": "voice-2"})
            socket.receive_json()

        assert seen["key"] == "the-voice-key"
        assert "the-voice-key" not in json.dumps(main.sessions.get("voice-2").as_dict())


class TestTheMcpEndpoint:
    """Over HTTP, which is how a host actually reaches it."""

    def test_a_get_declines_the_sse_channel(self, client: TestClient) -> None:
        response = client.get("/mcp")
        assert response.status_code == 405
        assert response.headers["allow"] == "POST"

    def test_a_handshake_over_http(self, client: TestClient) -> None:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert response.status_code == 200
        assert response.json()["result"]["serverInfo"]["name"] == "travel-a2ui"

    def test_a_notification_gets_202_and_an_empty_body(self, client: TestClient) -> None:
        response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert response.status_code == 202
        assert response.content == b""

    def test_a_body_that_is_not_json_is_a_parse_error(self, client: TestClient) -> None:
        response = client.post(
            "/mcp", content=b"{not json", headers={"content-type": "application/json"}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == -32700

    def test_the_view_is_chosen_at_install_time(self, client: TestClient) -> None:
        call = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "show_flight_options",
                "arguments": {"destination": "Madrid", "origin": "JFK", "date": "2099-04-12"},
            },
        }
        app_view = client.post("/mcp", json=call).json()["result"]
        legacy = client.post("/mcp?view=legacy", json=call).json()["result"]

        def mimes(result: dict) -> set[str]:
            return {
                part["resource"]["mimeType"]
                for part in result["content"]
                if part["type"] == "resource"
            }

        assert "application/vnd.a2ui+json" in mimes(app_view)
        assert "text/html" in mimes(legacy)

    def test_an_old_view_spelling_still_works(self, client: TestClient) -> None:
        """Rather than breaking an install that is already out there."""
        response = client.post(
            "/mcp?view=html",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "show_price_summary", "arguments": {"destination": "Madrid"}},
            },
        )
        mimes = {
            part["resource"]["mimeType"]
            for part in response.json()["result"]["content"]
            if part["type"] == "resource"
        }
        assert "text/html" in mimes

    def test_an_origin_override_is_honoured_only_over_http(self, client: TestClient) -> None:
        """Anything else is a script source somebody put in a URL."""
        read = {"jsonrpc": "2.0", "id": 1, "method": "resources/list"}

        allowed = client.post("/mcp?origin=https://tunnel.example", json=read).json()
        csp = allowed["result"]["resources"][0]["_meta"]["ui"]["csp"]
        assert csp["connectDomains"] == ["https://tunnel.example"]

        refused = client.post("/mcp?origin=javascript:alert(1)", json=read).json()
        domains = refused["result"]["resources"][0]["_meta"]["ui"]["csp"]["connectDomains"]
        assert all(domain.startswith("http") for domain in domains)

    def test_meta_points_at_the_endpoint_that_exists(self, client: TestClient) -> None:
        """A plugin reads this to find the server; a wrong path is a dead install."""
        endpoint = client.get("/api/meta").json()["mcpEndpoint"]
        assert client.get(endpoint).status_code == 405, "reachable, and declines GET"


class TestEachInlineCardIsItsOwnSurface:
    """The conversation is a list of things asked, not one thing rewritten.

    Every inline card used to be `inline-1`. The renderer stores surfaces by id,
    so each card in the transcript was a second view onto the same surface:
    answering a question rewrote that question, and every earlier card with it.
    From the outside it looked like the interface refreshing itself at random.

    It also silently disabled the finished-card treatment. A card is greyed and
    made inert once the turn that drew it ends — that code was correct and was
    running, over content that had already been replaced by the newest surface.
    So "answered" never looked answered.

    A standing surface is the opposite case and keeps its one id: there is one
    panel, and redrawing it in place is the whole point.
    """

    @staticmethod
    def _drawn(client: TestClient, monkeypatch, session_id=None, **body):
        """The surface id this turn would draw into.

        The model is stubbed: `surface_id` is settled before it is called, and
        it is the only thing under test here.
        """
        seen = {}

        async def fake_turn(request):  # noqa: ANN001, ANN202
            seen["surfaceId"] = request.surface_id
            yield {"type": "done", "stopReason": "completed"}

        monkeypatch.setattr(main, "run_turn", fake_turn)
        payload = {"message": "flights to Madrid", **body}
        if session_id:
            payload["sessionId"] = session_id
        response = client.post(
            "/api/chat", json=payload, headers={"x-goog-api-key": "k"}
        )
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        session = next(e["sessionId"] for e in events if e.get("type") == "session")
        return session, seen.get("surfaceId")

    def test_a_second_turn_draws_somewhere_new(self, client, monkeypatch) -> None:
        session, first = self._drawn(client, monkeypatch)
        _, second = self._drawn(client, monkeypatch, session)
        assert first and second
        assert first != second, "a new question must not overwrite the last one"

    def test_a_standing_surface_keeps_its_name(self, client, monkeypatch) -> None:
        """The panel is one surface for the life of the conversation."""
        session, first = self._drawn(client, monkeypatch, surface="sidebar")
        _, second = self._drawn(client, monkeypatch, session, surface="sidebar")
        assert first == "sidebar"
        assert second == "sidebar"

    def test_a_client_may_still_name_a_surface(self, client, monkeypatch) -> None:
        """Re-attaching to a card it already has is asking for that one."""
        _, drawn = self._drawn(client, monkeypatch, surfaceId="inline-7")
        assert drawn == "inline-7"


class TestWhereTheyAreFlyingFrom:
    """Asked, not inferred.

    The browser's timezone used to pick the departure airport, and a timezone
    covers a continent-slice: `America/New_York` offered JFK to Boston,
    Philadelphia and Atlanta alike, and Atlanta is 1,211 km from JFK. A
    coordinates path was built on top of it — a "Near me" button in the composer
    and a nearest-three shortlist — which made the guess better and the app
    stranger: a permission prompt beside the message box, for a question the
    agent can simply ask inside the surface it was drawing anyway.

    So none of it is inferred now. What is left to test is that nothing quietly
    guesses again, and that the contract says to ask.
    """

    def test_nothing_reads_the_browser_location(self) -> None:
        """No coordinates in, no coordinates anywhere."""
        import travel_a2ui.main as main_module
        import travel_a2ui.providers.fixture as fixture_module

        assert not hasattr(main_module, "_origin_hint")
        assert not hasattr(fixture_module, "origins_near")
        assert not hasattr(fixture_module, "origin_for_time_zone")

    def test_the_contract_says_to_ask(self) -> None:
        from travel_a2ui.skills import build_system_prompt

        said = build_system_prompt(
            variant="express-monolithic",
            surface="inline",
            surface_id="inline-1",
            catalog_id="travel",
            trip={},
            today="2027-03-01",
        )
        assert "always asked, never inferred" in said
        assert "ChoicePicker" in said
        assert "$/trip/origin" in said


class TestPressesTheHostAnswersItself:
    """Dropping an activity has nothing to decide.

    Every other press is a question — pick this flight, search those dates — and
    the answer needs judgement. Removing a museum from a day does not: the
    outcome is completely determined by what was pressed. Routing it through the
    model costs five to fifteen seconds and a chance of it redrawing the surface
    while it is there.

    The itinerary had nowhere to be removed *from* until today: it was drawn and
    forgotten, living only in the Express that produced it. It is part of the
    trip now, which is what makes editing, revisiting and sharing it possible.
    """

    TRIP = {
        "destination": "Madrid",
        "days": [
            {
                "title": "Day 1",
                "date": "2027-04-12",
                "activities": [
                    {"title": "Prado Museum", "time": "10:00"},
                    {"title": "Lunch at Sobrino", "time": "13:30"},
                ],
            },
            {"title": "Day 2", "date": "2027-04-13", "activities": [{"title": "Toledo"}]},
        ],
    }

    def _drop(self, client: TestClient, monkeypatch, day: int, index: int):
        called: dict[str, Any] = {"model": False}

        async def fake_turn(request):  # noqa: ANN001, ANN202
            called["model"] = True
            yield {"type": "done", "stopReason": "completed"}

        monkeypatch.setattr(main, "run_turn", fake_turn)
        main.sessions.save("plan-1", trip=dict(self.TRIP))
        response = client.post(
            "/api/chat",
            json={
                "sessionId": "plan-1",
                "action": {
                    "name": "drop_activity",
                    "surfaceId": "inline-3",
                    "context": {"day": day, "index": index},
                },
            },
            headers={"x-goog-api-key": "k"},
        )
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        return called, events

    def test_the_model_is_not_woken(self, client: TestClient, monkeypatch) -> None:
        called, events = self._drop(client, monkeypatch, 0, 0)
        assert called["model"] is False
        assert [event["type"] for event in events][-1] == "done"

    def test_the_activity_is_gone_from_the_trip(self, client: TestClient, monkeypatch) -> None:
        _, events = self._drop(client, monkeypatch, 0, 0)
        trip = next(event["trip"] for event in events if event["type"] == "trip")
        assert [a["title"] for a in trip["days"][0]["activities"]] == ["Lunch at Sobrino"]
        assert [a["title"] for a in trip["days"][1]["activities"]] == ["Toledo"]
        # And it is what the next turn will read.
        assert main.sessions.get("plan-1").trip["days"][0]["activities"][0]["title"] == (
            "Lunch at Sobrino"
        )

    def test_every_renderer_hears_about_it_the_usual_way(
        self, client: TestClient, monkeypatch
    ) -> None:
        """`updateDataModel`, which every client already applies."""
        _, events = self._drop(client, monkeypatch, 0, 0)
        surfaces = {event["surfaceId"] for event in events if event["type"] == "ui"}
        assert "inline-3" in surfaces, "the surface they pressed on"
        assert "sidebar" in surfaces, "and the panel beside it"

    def test_an_emptied_day_stays(self, client: TestClient, monkeypatch) -> None:
        """An empty day is a rest day. Deleting the card would lose the date."""
        _, events = self._drop(client, monkeypatch, 1, 0)
        trip = next(event["trip"] for event in events if event["type"] == "trip")
        assert trip["days"][1]["activities"] == []
        assert trip["days"][1]["date"] == "2027-04-13"

    def test_a_press_that_does_not_resolve_goes_to_the_model(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Removing the wrong activity is worse than removing none."""
        called, _ = self._drop(client, monkeypatch, 9, 9)
        assert called["model"] is True
