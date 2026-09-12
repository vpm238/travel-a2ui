"""The Python tools have to answer what the TypeScript tools answer. Exactly.

The layer these tests cover is the agent's manners: when a tool refuses to
price a trip nobody has given dates for, what it tells the model to do instead,
which stop of a multi-city route a call is about, and what a saved trip reports
still missing. None of it is generated and all of it is judgement, which makes
it the part of the port most likely to drift while every test still passes.

`tools/parity/__golden__/tools.json` is written by the TypeScript and is the
contract. A divergence here is not a formatting difference — every one of these
results is read by a model and turned into a surface, so a port that returns
the right flights under a different key, or drops the sentence telling the
model to draw the controls and wait, ships an agent that is quietly worse at
its job.
"""

from __future__ import annotations

import asyncio
import copy
import json
import pathlib

import pytest

from travel_a2ui.providers.fixture import FixtureProvider
from travel_a2ui import tools
from travel_a2ui.tools import ToolContext, run_tool

ROOT = pathlib.Path(__file__).resolve().parents[3]
GOLDEN = json.loads((ROOT / "tools" / "parity" / "__golden__" / "tools.json").read_text("utf-8"))

#: The same fixed day the golden was captured on. `save_trip` refuses a start
#: date in the past, so without this the test would pass until it didn't.
TODAY = "2027-03-01"


def run_case(case: dict) -> dict:
    """Replays one golden case and reports what this implementation did."""
    trip = copy.deepcopy(case["tripBefore"])
    saved: list[dict] = []

    def save(patch: dict) -> None:
        saved.append(copy.deepcopy(patch))
        trip.update(patch)

    context = ToolContext(
        trip=trip,
        provider=FixtureProvider(),
        save=save,
        today=TODAY,
    )
    result, is_error = asyncio.run(run_tool(case["tool"], case["input"], context))
    return {"result": result, "isError": is_error, "trip": trip, "saved": saved}


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2)


@pytest.mark.parametrize("name", list(GOLDEN))
def test_matches_the_typescript(name: str) -> None:
    expected = GOLDEN[name]
    actual = run_case(expected)

    for field in ("result", "isError", "trip", "saved"):
        assert canonical(actual[field]) == canonical(expected[field]), (
            f"{name}: {field} diverged from the TypeScript"
        )


def test_the_golden_covers_every_tool() -> None:
    """A tool with no case is a tool nobody is holding to anything.

    Cheap to write and it has already earned its place: the port was finished
    before this file existed, and two tools in it answered in a shape the
    TypeScript never used.
    """
    from travel_a2ui.tools import TOOLS

    covered = {case["tool"] for case in GOLDEN.values()}
    assert {tool["name"] for tool in TOOLS} <= covered


class TestGrounding:
    """Search sits beside the tools, and must not leak into the voice setup.

    The eight functions answer with fixtures, which is right for a price nobody
    should trust and poor for the half of planning that is not a price: how many
    days a place deserves, what is shut in April, whether the festival lands in
    their week. Those are facts about the world, and no fixture will ever have
    them.
    """

    def test_the_built_ins_are_declared_in_the_shape_the_api_wants(self) -> None:
        assert tools.grounding_tools() == [
            {"type": "google_search"},
            {"type": "url_context"},
        ]

    def test_a_deployment_can_turn_it_off(self, monkeypatch) -> None:
        """Reaching the open web is the one thing here that leaves the process."""
        monkeypatch.setattr(tools, "GROUNDING", False)
        assert tools.grounding_tools() == []

    def test_the_function_list_stays_functions_only(self) -> None:
        """`voice_tools` reads `name` and `parameters` off every entry.

        A built-in has neither. Putting one in `gemini_tools` would not fail
        here — it would fail when a Live session opened, as a setup frame
        rejected whole with nothing naming the tool that caused it.
        """
        for tool in tools.gemini_tools():
            assert tool["type"] == "function"
            assert tool["name"] and tool["parameters"] is not None

    def test_voice_never_sees_a_built_in(self) -> None:
        from travel_a2ui.voice import voice_tools

        for tool in voice_tools():
            assert "name" in tool and "parameters" in tool
