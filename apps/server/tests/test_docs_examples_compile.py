"""Every Express example a person or the model reads compiles against the catalog.

An example in the README is the first A2UI a developer copies, and an example
in `prompts/` is one the model imitates. One that the catalog rejects teaches
the wrong thing to both: the README once opened on `Text(..., variant="h3")`,
which v1.0 removed, and the compiler refuses.

Checked: fenced blocks and `<a2ui>` blocks that define a `root`. Blocks that
elide part of themselves (`...`) are fragments, not examples, and are skipped.
"""

from __future__ import annotations

import re
import warnings

import pytest

warnings.filterwarnings("ignore")

from travel_a2ui import ROOT  # noqa: E402
from travel_a2ui.brain.catalog import parser_for  # noqa: E402
from travel_a2ui.brain.macros import expand  # noqa: E402

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


def test_there_are_examples_to_check() -> None:
    assert len(EXAMPLES) > 10


@pytest.mark.parametrize("where,source", EXAMPLES, ids=[where for where, _ in EXAMPLES])
def test_the_example_compiles(where: str, source: str) -> None:
    messages = parser_for("inline-1").compile(source, is_final=True)
    expand(messages)
