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

import pytest

from travel_a2ui import skills

ROOT = pathlib.Path(__file__).resolve().parents[3]
GOLDEN = json.loads((ROOT / "tools" / "parity" / "__golden__" / "prompt.json").read_text("utf-8"))

TODAY = "2027-03-01"

#: The same trips the capture script used, chosen for the branches they take
#: through `describe_trip`: nothing settled, something settled, everything
#: settled, something wrong with it, a stage ruled out, a route with stops.
TRIPS: dict[str, dict] = {
    "empty": {},
    "started": {"destination": "Madrid"},
    "ready": {
        "origin": "JFK",
        "destination": "Madrid",
        "startDate": "2027-04-12",
        "endDate": "2027-04-19",
        "travelers": 2,
    },
    "priced": {
        "origin": "JFK",
        "destination": "Madrid",
        "startDate": "2027-04-12",
        "endDate": "2027-04-19",
        "travelers": 2,
        "flightPrice": 780,
        "nightlyPrice": 190,
        "budget": 3000,
        "selectedFlight": "IB614",
    },
    "broken": {
        "destination": "Madrid",
        "origin": "JFK",
        "startDate": "2027-04-20",
        "endDate": "2027-04-12",
        "travelers": 2,
    },
    "skipping": {"destination": "Madrid", "origin": "JFK", "skip": ["stay", "budget"]},
    "multiCity": {
        "origin": "SFO",
        "destination": "Chicago",
        "startDate": "2027-04-12",
        "endDate": "2027-04-14",
        "travelers": 1,
        "legs": [
            {"destination": "New York", "startDate": "2027-04-14", "endDate": "2027-04-18"},
            {"destination": "San Francisco", "startDate": "2027-04-18", "travelers": 2},
        ],
    },
}

ORIGIN_HINT = {"code": "SFO", "city": "San Francisco", "timeZone": "America/Los_Angeles"}


def build(label: str) -> str:
    """Rebuilds one golden prompt from its label.

    The labels encode the case, so there is one table of trips rather than two
    that can disagree about what "ready" means.
    """
    kind, _, rest = label.partition(" / ")
    if kind == "variant":
        return skills.build_system_prompt(
            variant=rest,
            surface="inline",
            surface_id="inline-1",
            catalog_id="travel",
            trip=TRIPS["ready"],
            today=TODAY,
        )
    if kind == "origin hint":
        trip = TRIPS["started"] if rest == "offered" else TRIPS["ready"]
        return skills.build_system_prompt(
            variant="express-monolithic",
            surface="inline",
            surface_id="inline-1",
            catalog_id="travel",
            trip=trip,
            today=TODAY,
            origin_hint=ORIGIN_HINT,
        )
    return skills.build_system_prompt(
        variant="express-monolithic",
        surface=rest,
        surface_id="inline-1" if rest == "inline" else rest,
        catalog_id="travel",
        trip=TRIPS[kind],
        today=TODAY,
    )


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


@pytest.mark.parametrize("label", list(GOLDEN["prompts"]))
def test_matches_the_typescript(label: str) -> None:
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
