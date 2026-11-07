"""Every example the model learns from writes `root` first, so cards stream.

The SDK sends a surface's components as each line of Express completes, but a
renderer draws from `root`. A block that ends with `root` therefore stays blank
until its last line and then appears all at once; one that starts with it
appears as the model writes. The model copies the order its examples use, so
they all lead with `root`.
"""

from __future__ import annotations

import json
import re

import pytest

from travel_a2ui import ROOT
from travel_a2ui.brain import data
from travel_a2ui.brain.ui import Canvas, Drawing

EXAMPLES = sorted((ROOT / "catalogs" / "a2ui-travel" / "examples").glob("*.json"))
PROMPTS = sorted((ROOT / "prompts").glob("*.md"))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_each_worked_example_lists_root_first(path) -> None:
    for message in json.loads(path.read_text())["messages"]:
        for kind in ("createSurface", "updateComponents"):
            components = message.get(kind, {}).get("components") or []
            if any(c["id"] == "root" for c in components):
                assert components[0]["id"] == "root"


@pytest.mark.parametrize("path", PROMPTS, ids=lambda p: p.name)
def test_each_prompt_example_writes_root_first(path) -> None:
    for block in re.findall(r"<a2ui>\n(.*?)\n\s*</a2ui>", path.read_text(), re.S):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        lines = [line for line in lines if not line.startswith("surface(")]
        if any(line.startswith("root") for line in lines):
            assert lines[0].startswith("root"), lines[0]


def _ui_events(block: str) -> list[list[str]]:
    drawing = Drawing(Canvas(), "inline-1", lambda _s: data.session_values({}, None))
    seen = []
    for start in range(0, len(block), 10):
        for event in drawing.feed(block[start : start + 10]):
            if event[0] == "ui":
                seen.append(
                    [
                        c["id"]
                        for m in event[2]
                        for k in ("createSurface", "updateComponents")
                        for c in m.get(k, {}).get("components", [])
                    ]
                )
    return seen


def test_a_root_first_block_reaches_the_screen_a_line_at_a_time() -> None:
    block = '<a2ui>\nroot = Column([a, b, c])\na = Text("one")\nb = Text("two")\nc = Text("three")\n</a2ui>'
    events = _ui_events(block)
    assert events[0][0] == "root"
    assert len(events) >= 3


def test_a_root_last_block_arrives_in_one_piece() -> None:
    block = '<a2ui>\na = Text("one")\nb = Text("two")\nc = Text("three")\nroot = Column([a, b, c])\n</a2ui>'
    assert len(_ui_events(block)) == 1
