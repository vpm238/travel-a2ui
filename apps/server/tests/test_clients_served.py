"""A client built while the server runs is served at once.

The quickstart starts the server, then builds React, then Flutter. Each build
must show up on reload, with no restart, and a client not built yet must say
how to build it rather than answer with a bare 404.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from travel_a2ui.doors import http
from travel_a2ui.doors.http import BuiltClient


def served(folder: Path) -> TestClient:
    app = FastAPI()
    app.mount("/flutter", BuiltClient(folder, "Build it with: make"), name="flutter")
    return TestClient(app)


def test_a_client_not_built_says_how_to_build_it(tmp_path: Path) -> None:
    response = served(tmp_path / "web").get("/flutter/")
    assert response.status_code == 404
    assert "Build it with: make" in response.text


def test_a_client_built_after_start_is_served_without_a_restart(tmp_path: Path) -> None:
    folder = tmp_path / "web"
    client = served(folder)
    assert client.get("/flutter/").status_code == 404
    folder.mkdir()
    (folder / "index.html").write_text("<p>hello</p>")
    response = client.get("/flutter/")
    assert response.status_code == 200 and "hello" in response.text


def test_the_app_mounts_both_clients_whether_or_not_they_are_built() -> None:
    mounted = {getattr(route, "path", None) for route in http.app.routes}
    assert {"/flutter", ""} <= mounted


def test_an_api_typo_is_json_even_with_no_client_built(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(http, "WEB_DIST", tmp_path / "missing")
    response = TestClient(http.app).get("/api/nope")
    assert response.status_code == 404
    assert response.json() == {"error": "No route for /api/nope"}
