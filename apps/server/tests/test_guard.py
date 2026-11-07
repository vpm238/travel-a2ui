"""What a request may ask of this server, and how often on the server's key."""

from __future__ import annotations

from fastapi.testclient import TestClient

from travel_a2ui.doors import guard, http


class TestChoices:
    def test_a_model_the_server_does_not_offer_falls_back(self) -> None:
        assert guard.chosen_model("gemini-ultra-expensive", ["a", "b"], "a") == "a"
        assert guard.chosen_model("b", ["a", "b"], "a") == "b"
        assert guard.chosen_model(None, ["a"], "a") == "a"

    def test_an_unknown_effort_falls_back(self) -> None:
        assert guard.chosen_effort("max-please", "low") == "low"
        assert guard.chosen_effort("high", "low") == "high"


class TestOrigins:
    def test_same_site_and_listed_origins_are_allowed(self, monkeypatch) -> None:
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://booth.example.com")
        assert guard.origin_allowed("https://app.example.com", "app.example.com")
        assert guard.origin_allowed("https://booth.example.com", "app.example.com")
        assert guard.origin_allowed(None, "app.example.com")

    def test_another_site_is_refused(self) -> None:
        assert not guard.origin_allowed("https://evil.example", "app.example.com")

    def test_the_voice_socket_refuses_another_site(self) -> None:
        import pytest
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as refused:
            with TestClient(http.app).websocket_connect("/api/voice", headers={"origin": "https://evil.example"}):
                pass
        assert refused.value.code == 1008


class TestTheSharedKey:
    def test_the_limit_is_per_address_per_hour(self) -> None:
        limit = guard.RateLimit(2)
        assert limit.allow("a", 0) and limit.allow("a", 1)
        assert not limit.allow("a", 2)
        assert limit.allow("b", 2)
        assert limit.allow("a", 3700)

    def test_a_turn_past_the_limit_is_refused(self, monkeypatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "server-key")
        monkeypatch.setattr(guard, "SHARED_KEY_LIMIT", guard.RateLimit(0))
        response = TestClient(http.app).post("/api/chat", json={"message": "hi", "sessionId": "lim"})
        assert response.status_code == 429

    def test_a_visitors_own_key_is_not_limited(self, monkeypatch) -> None:
        async def fake_turn(request):  # noqa: ANN001, ANN202
            yield {"type": "done", "stopReason": "completed"}

        monkeypatch.setenv("GEMINI_API_KEY", "server-key")
        monkeypatch.setattr(guard, "SHARED_KEY_LIMIT", guard.RateLimit(0))
        monkeypatch.setattr(http, "run_turn", fake_turn)
        response = TestClient(http.app).post(
            "/api/chat", json={"message": "hi", "sessionId": "own"}, headers={"x-goog-api-key": "mine"}
        )
        assert response.status_code == 200

    def test_the_client_cannot_pick_an_unoffered_model(self, monkeypatch) -> None:
        seen: dict = {}

        async def fake_turn(request):  # noqa: ANN001, ANN202
            seen["model"], seen["effort"] = request.model, request.effort
            yield {"type": "done", "stopReason": "completed"}

        monkeypatch.setattr(http, "run_turn", fake_turn)
        TestClient(http.app).post(
            "/api/chat",
            json={"message": "hi", "sessionId": "m", "model": "gemini-9-ultra", "effort": "infinite"},
            headers={"x-goog-api-key": "mine"},
        )
        assert seen["model"] == http.AGENT_DEFAULT_MODEL
        assert seen["effort"] == http.DEFAULT_EFFORT
