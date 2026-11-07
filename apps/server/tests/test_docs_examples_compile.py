"""Every Express example a person or the model reads is drawn without complaint.

An example in the README is the first A2UI a developer copies, and an example
in `prompts/` is one the model imitates. Each is read the way a turn reads the
model: through the SDK processor, its macros expanded, applied to a mirror of
the renderer (`brain/ui.py`). A block refused there teaches the wrong thing.

Checked: fenced blocks and `<a2ui>` blocks that define a `root`. Blocks that
elide part of themselves (`...`) are fragments and are skipped. A block that
updates a surface (`update=true`) is checked against a surface created first.
"""

from __future__ import annotations

import re
import warnings

import pytest

warnings.filterwarnings("ignore")

from travel_a2ui import ROOT  # noqa: E402
from travel_a2ui.brain import data  # noqa: E402
from travel_a2ui.brain.ui import Canvas, Drawing  # noqa: E402

DOCUMENTS = [
    ROOT / "README.md",
    *sorted((ROOT / "docs").glob("*.md")),
    ROOT / "docs" / "site" / "src" / "content" / "docs" / "quickstart.mdx",
    ROOT / "docs" / "site" / "src" / "prompts" / "quickstart.md",
    *sorted((ROOT / "prompts").glob("*.md")),
]

_FENCED = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)
_TAGGED = re.compile(r"<a2ui>\n(.*?)\n\s*</a2ui>", re.DOTALL)
_ROOT = re.compile(r"^\s*root\s*=", re.MULTILINE)
_UPDATES = re.compile(r'surface\("([^"]+)",\s*update=true\)')


def _examples() -> list[tuple[str, str]]:
    found = []
    for document in DOCUMENTS:
        text = document.read_text(encoding="utf-8")
        for pattern in (_FENCED, _TAGGED):
            for match in pattern.finditer(text):
                block = match.group(1)
                if "<a2ui>" in block or not _ROOT.search(block) or "..." in block:
                    continue
                source = "\n".join(line[4:] if line.startswith("    ") else line for line in block.splitlines())
                line = text[: match.start()].count("\n") + 1
                found.append((f"{document.relative_to(ROOT)}:{line}", source))
    return found


EXAMPLES = _examples()


def _values(_surface: str) -> dict:
    return data.session_values({"destination": "Madrid", "origin": "JFK"}, {"origins": [], "destinations": []})


def test_there_are_examples_to_check() -> None:
    assert len(EXAMPLES) > 10


@pytest.mark.parametrize("where,source", EXAMPLES, ids=[where for where, _ in EXAMPLES])
def test_the_example_draws(where: str, source: str) -> None:
    canvas = Canvas()
    for updated in _UPDATES.findall(source):
        Drawing(canvas, updated, _values).feed(f'<a2ui>\nsurface("{updated}")\nroot = Column([])\n</a2ui>')
    named = re.findall(r'^surface\("([^"]+)"', source, re.MULTILINE)
    drawing = Drawing(canvas, named[0] if named else "inline-1", _values)
    events = [*drawing.feed(f"<a2ui>\n{source}\n</a2ui>"), *drawing.close()]
    refused = [event[1] for event in events if event[0] == "rejected"]
    assert not refused, refused
    assert any(event[0] == "ui" for event in events), events
