"""The sample trip a first visit opens on is still something this app would draw.

The sample is a recording (`tools/sample/record.py`) of a real conversation with
the agent, replayed by the browser. A recording does not change when the
catalog does, so without this a renamed prop or a tightened schema would leave
the first thing every visitor sees drawn from A2UI the renderer no longer
accepts — and nothing would say so until somebody looked.

So every surface in it is replayed here, in order, through the SDK's own
validator against the current catalog: a surface created once, then updated,
in the order a renderer receives it. When this fails, re-record; do not edit the
file.
"""

from __future__ import annotations

import json

import pytest
from a2ui.utils.renderer_state import RendererState  # noqa: E402

from travel_a2ui import ROOT  # noqa: E402
from travel_a2ui.brain.catalog import CATALOG  # noqa: E402

SAMPLE = ROOT / "apps" / "web" / "public" / "sample-trip.json"
recording = json.loads(SAMPLE.read_text(encoding="utf-8"))


def _surface_events() -> list[tuple[int, str, list]]:
    return [
        (number, event["surfaceId"], event["messages"])
        for number, turn in enumerate(recording["turns"], 1)
        for event in turn["events"]
        if event["type"] == "ui"
    ]


def test_every_recorded_surface_still_validates() -> None:
    """Every message, against its surface as it stood when the message arrived.

    One SDK renderer mirror per surface, so a reference resolves against what
    earlier messages built. Two things are left to the lifecycle test rather
    than failed here: a `createSurface` for a surface that already exists starts
    that surface's mirror again, and values for a surface never created are
    skipped. Both are real conformance questions; this one is whether what was
    drawn is valid A2UI for this catalog.
    """
    mirrors: dict[str, RendererState] = {}
    failures = []
    for number, _, messages in _surface_events():
        for message in messages:
            body = (
                message.get("createSurface") or message.get("updateComponents") or message.get("updateDataModel") or {}
            )
            target = body.get("surfaceId")
            if "createSurface" in message:
                mirrors[target] = RendererState([CATALOG])
            elif target not in mirrors:
                continue
            try:
                mirrors[target].apply([message])
            except Exception as error:  # noqa: BLE001 - the message is the report
                failures.append(f"turn {number}, {target}: {type(error).__name__}: {str(error)[:300]}")
    assert not failures, "Re-record with tools/sample/record.py:\n" + "\n".join(failures[:5])


def test_it_holds_nothing_that_belongs_to_the_recording() -> None:
    text = SAMPLE.read_text(encoding="utf-8")
    # A pointer into the recorder's Gemini account, which nobody replaying this
    # could follow — and a key, which must never be anywhere in the repository.
    assert "interactionId" not in text
    assert "AIza" not in text and "AQ.Ab" not in text
    assert all(event["type"] != "usage" for turn in recording["turns"] for event in turn["events"])


def test_its_cards_cannot_collide_with_a_live_conversation() -> None:
    # A live turn after the sample numbers its cards from inline-1 again.
    for _, surface_id, _ in _surface_events():
        assert surface_id in {"sidebar", "home"} or surface_id.startswith("sample-"), surface_id


@pytest.mark.parametrize("turn", recording["turns"], ids=lambda turn: turn.get("message") or turn["action"]["name"])
def test_each_turn_was_answered(turn: dict) -> None:
    kinds = [event["type"] for event in turn["events"]]
    assert "done" in kinds
    assert "ui" in kinds or "text" in kinds
