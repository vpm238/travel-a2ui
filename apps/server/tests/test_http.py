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

        The two implementations disagree here — the Worker emits the catalog's
        short name and the SDK emits its canonical `$id` — so asserting it keeps
        this server internally consistent rather than merely consistent with the
        one it replaces.
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

    def test_the_timezone_becomes_a_suggestion_and_not_a_decision(
        self, client: TestClient, monkeypatch
    ) -> None:
        seen: dict[str, Any] = {}

        async def fake_turn(request):  # noqa: ANN001, ANN202
            seen["hint"] = request.origin_hint
            yield {"type": "done", "stopReason": "completed"}

        monkeypatch.setattr(main, "run_turn", fake_turn)
        client.post(
            "/api/chat",
            json={"message": "hi", "client": {"timeZone": "America/Los_Angeles"}},
            headers={"x-goog-api-key": "k"},
        )
        assert seen["hint"]["code"] == "LAX"

    def test_no_timezone_is_no_hint(self, client: TestClient, monkeypatch) -> None:
        seen: dict[str, Any] = {}

        async def fake_turn(request):  # noqa: ANN001, ANN202
            seen["hint"] = request.origin_hint
            yield {"type": "done", "stopReason": "completed"}

        monkeypatch.setattr(main, "run_turn", fake_turn)
        client.post("/api/chat", json={"message": "hi"}, headers={"x-goog-api-key": "k"})
        assert seen["hint"] is None


def test_health_answers_before_traffic_arrives(client: TestClient) -> None:
    assert client.get("/healthz").json()["ok"] is True
