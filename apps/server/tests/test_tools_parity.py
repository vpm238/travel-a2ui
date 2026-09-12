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
