"""The Python server has to give the model the prompt the TypeScript gave it.

The prompt is the agent — not a configuration of it, but the whole of what
makes it refuse to price a week nobody chose, ask for everything missing in one
surface, and draw a read-only panel when it is drawing the panel. Two servers
calling the same model with different prompts are two different products, and
nothing about the difference looks like a bug: both answer, both draw
something, and only the details diverge.

Most of the text is now shared — `prompts/*.md` and the generated skills — so
what these tests really hold is the assembly: the order of the layers, where
the cache breakpoint falls, and the per-turn trip description, which is the
part that is code rather than markdown and so the part that can differ.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

from travel_a2ui import skills

ROOT = pathlib.Path(__file__).resolve().parents[3]
GOLDEN = json.loads((ROOT / "tools" / "parity" / "__golden__" / "prompt.json").read_text("utf-8"))

# The trips, the origin hint and the assembly are defined once, in the script
# that records the golden — `tools/parity/capture.py`. They lived here as well
# for a while and the two copies disagreed about what "skipping" skipped, which
# meant this suite and the recorder built different prompts from the same label
# and each believed the other was wrong.
sys.path.insert(0, str(ROOT / "tools" / "parity"))
from capture import LABELS, TODAY, TRIPS, build  # noqa: E402,F401

def first_difference(actual: str, expected: str) -> str:
    """Where two prompts part company, with enough either side to read it.

    A raw assert on two 37,000-character strings prints something nobody can
    act on; the line number and the sentence around it is what makes a failure
    here a two-minute fix.
    """
    for index, (a, b) in enumerate(zip(actual, expected)):
        if a != b:
            line = expected.count("\n", 0, index) + 1
            return (
                f"line {line}, character {index}\n"
                f"  expected: ...{expected[max(0, index - 70):index + 70]!r}\n"
                f"  actual:   ...{actual[max(0, index - 70):index + 70]!r}"
            )
    shorter, longer = sorted((actual, expected), key=len)
    return (
        f"identical for {len(shorter)} characters, then one runs on:\n"
        f"  {longer[len(shorter):len(shorter) + 200]!r}"
    )


@pytest.mark.parametrize("label", LABELS)
def test_the_prompt_matches_its_golden(label: str) -> None:
    expected = GOLDEN["prompts"][label]
    actual = build(label)
    assert actual == expected, f"{label} diverged at {first_difference(actual, expected)}"


def test_reports_the_same_skills() -> None:
    assert skills.describe_all_skills() == GOLDEN["skills"]


def test_the_stable_half_comes_first() -> None:
    """The cache breakpoint, asserted rather than assumed.

    Stable-then-volatile is the whole reason the prompt is assembled rather
    than concatenated: Gemini caches a repeated prefix implicitly, so the
    catalog and the rules are paid for once per conversation instead of once
    per turn. Swapping the halves still produces a correct prompt and a correct
    demo — just a much more expensive one, which is precisely the kind of
    regression that survives a review.
    """
    prompt = build("ready / inline")
    assert prompt.index(skills.ROLE) == 0
    assert prompt.index("## The trip so far") > prompt.index(skills.SURFACE_BRIEFS["inline"])
    assert prompt.index(skills.SURFACE_BRIEFS["inline"]) > prompt.index("## Make the surface")


class TestThePromptOnlyNamesComponentsTheModelHas:
    """A prompt may not recommend a component that pruning removed.

    The catalog carries 30 components; the model is shown 24, because
    `with_pruning` drops the ones a travel agent never needs (AudioPlayer,
    Video, Modal, Tabs, Divider, Image). That is a large, cheap saving and it
    has one sharp edge: the surface briefs are prose, written by hand, and
    nothing stopped one of them naming a component that is no longer there.

    The failure is quiet in the worst way. The model is told to draw the panel
    with `Image`, cannot find `Image` in its catalog, and either invents a
    component that fails to compile or silently drops the thing it was asked to
    show. Neither looks like a prompt problem from the outside.
    """

    @staticmethod
    def _pruned_names() -> set[str]:
        import json
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[3]
        catalog = json.loads(
            (root / "catalogs" / "a2ui-travel" / "catalog.json").read_text("utf-8")
        )
        skill = (root / "skills" / "express-monolithic" / "a2ui" / "SKILL.md").read_text("utf-8")
        return {name for name in catalog["components"] if name not in skill}

    @pytest.mark.parametrize("brief", ["role", "surface-inline", "surface-sidebar", "surface-home"])
    def test_no_brief_recommends_a_pruned_component(self, brief: str) -> None:
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[3]
        path = root / "prompts" / f"{brief}.md"
        if not path.exists():
            pytest.skip(f"no {brief} brief")
        text = path.read_text("utf-8")

        # Only backticked names count. Prose may say "an image" without meaning
        # the component, and failing on that would make this untriageable.
        mentioned = set(re.findall(r"`([A-Z][A-Za-z]+)`", text))
        offenders = sorted(mentioned & self._pruned_names())
        assert not offenders, (
            f"{brief}.md recommends {offenders}, which pruning removes from the "
            "catalog the model is given"
        )
