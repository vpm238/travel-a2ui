"""Each surface created once, and nothing sent to a surface that does not exist.

See `brain/finishing/lifecycle.py`. The whole-stream test is the one that
matters: a real recorded conversation, every message, in order, through the
SDK's own renderer mirror — which is what `@a2ui/web_core` does in the browser.
Before this filter it rejected 141 messages of that recording, among them the
agent's real card on every turn.
"""

from __future__ import annotations

import json
import warnings

warnings.filterwarnings("ignore")

from a2ui.utils.renderer_state import RendererState  # noqa: E402

from travel_a2ui import ROOT  # noqa: E402
from travel_a2ui.brain.catalog import CATALOG, CATALOG_ID  # noqa: E402
from travel_a2ui.brain.finishing.lifecycle import SurfaceLifecycle, held_by_client  # noqa: E402

V = "1.0"


def create(surface: str, components: list | None = None, data: dict | None = None) -> dict:
    body: dict = {"surfaceId": surface, "catalogId": CATALOG_ID}
    if components is not None:
        body["components"] = components
    if data is not None:
        body["dataModel"] = data
    return {"version": V, "createSurface": body}


def update_data(surface: str, path: str, value) -> dict:
    return {"version": V, "updateDataModel": {"surfaceId": surface, "path": path, "value": value}}


TEXT = [{"id": "root", "component": "Text", "text": "Hello"}]


class TestTheRules:
    def test_a_first_create_goes_out_as_it_is(self) -> None:
        lifecycle = SurfaceLifecycle()
        message = create("inline-1", TEXT)
        assert lifecycle.messages([message]) == [message]
        assert lifecycle.held == {"inline-1"}

    def test_a_second_create_updates_instead_and_keeps_the_lookup_rows(self) -> None:
        lifecycle = SurfaceLifecycle(["inline-1"])
        out = lifecycle.messages([create("inline-1", TEXT, {"trip": {"origin": "JFK"}, "plan": []})])
        assert out[0] == {"version": V, "updateComponents": {"surfaceId": "inline-1", "components": TEXT}}
        # Per key: a write at "/" would wipe /flights, which the new card reads.
        assert [m["updateDataModel"]["path"] for m in out[1:]] == ["/trip", "/plan"]

    def test_values_for_a_surface_nobody_created_are_not_sent(self) -> None:
        assert SurfaceLifecycle().messages([update_data("home", "/trip", {})]) == []

    def test_a_key_with_a_slash_is_escaped(self) -> None:
        out = SurfaceLifecycle(["s"]).messages([create("s", None, {"a/b": 1})])
        assert out[0]["updateDataModel"]["path"] == "/a~1b"

    def test_the_client_says_what_it_holds(self) -> None:
        assert held_by_client({"client": {"surfaces": ["sidebar", 3]}}) == ["sidebar"]
        assert held_by_client({"client": {}}) is None
        assert held_by_client({}) is None


def test_a_whole_recorded_conversation_is_accepted_by_a_strict_renderer() -> None:
    sample = json.loads((ROOT / "apps" / "web" / "public" / "sample-trip.json").read_text("utf-8"))
    lifecycle = SurfaceLifecycle()
    renderer = RendererState([CATALOG])
    rejected = []
    for number, turn in enumerate(sample["turns"], 1):
        for event in turn["events"]:
            conformant = lifecycle.event(event)
            if conformant is None or conformant.get("type") != "ui":
                continue
            for message in conformant["messages"]:
                try:
                    renderer.apply([message])
                except Exception as error:  # noqa: BLE001 - the message is the report
                    rejected.append(f"turn {number}: {type(error).__name__}: {str(error)[:200]}")
    assert not rejected, f"{len(rejected)} rejected:\n" + "\n".join(rejected[:5])


class TestDataBeforeItsSurface:
    """A lookup's rows, filed before the card that shows them exists."""

    def _ui(self, *messages: dict) -> dict:
        return {"type": "ui", "surfaceId": "inline-1", "messages": list(messages)}

    def test_rows_filed_first_arrive_right_after_the_create(self) -> None:
        from travel_a2ui.brain.finishing.lifecycle import SurfaceLifecycle

        life = SurfaceLifecycle()
        rows = {"version": "1.0", "updateDataModel": {"surfaceId": "inline-1", "path": "/flights", "value": [{"id": "IB1"}]}}
        assert life.event(self._ui(rows)) is None, "held, not sent to a surface the client lacks"
        create = {
            "version": "1.0",
            "createSurface": {"surfaceId": "inline-1", "catalogId": "c", "components": [], "dataModel": {"trip": {}}},
        }
        sent = life.event(self._ui(create))["messages"]
        assert sent == [create, rows]

    def test_but_never_over_what_the_create_brings(self) -> None:
        from travel_a2ui.brain.finishing.lifecycle import SurfaceLifecycle

        life = SurfaceLifecycle()
        old = {"version": "1.0", "updateDataModel": {"surfaceId": "sidebar", "path": "/trip", "value": {"travelers": 1}}}
        life.event({"type": "ui", "surfaceId": "sidebar", "messages": [old]})
        create = {
            "version": "1.0",
            "createSurface": {"surfaceId": "sidebar", "catalogId": "c", "components": [], "dataModel": {"trip": {"travelers": 3}}},
        }
        sent = life.event({"type": "ui", "surfaceId": "sidebar", "messages": [create]})["messages"]
        assert sent == [create], "an older value would have overwritten the newer seed"
