#!/usr/bin/env python3
"""Re-records the goldens that depend on text a person edits.

The goldens were captured from the TypeScript implementation, and while both
existed that was the point: two agents that had to agree, byte for byte. The
TypeScript is gone, so the comparison is no longer cross-language — but the
goldens are not therefore worthless. They still catch the thing they were built
to catch, which is a change nobody meant to make.

Only the prompt is re-recorded here, and only because it is assembled from
markdown that people edit on purpose. The rest — the trip model, the tools, the
skeleton, the surface passes — are goldens over *code*, and code changing
without the golden changing is exactly the alarm they exist to raise. Those are
frozen. If one of them starts failing, the answer is to look at the diff, not to
re-record it.

    python3 tools/parity/capture.py            # re-record
    python3 tools/parity/capture.py --check    # fail if it would change

`--check` is what CI runs: it makes "I edited a prompt and forgot to re-record"
a failed build rather than a mystery a week later.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "server" / "src"))

GOLDEN = ROOT / "tools" / "parity" / "__golden__" / "prompt.json"

# Imported after the path is set up, and named here rather than at module scope
# so the docstring above is readable without the import noise.
from travel_a2ui import skills  # noqa: E402

TODAY = "2027-03-01"

#: The trips are the branches through `describe_trip`, not a sample of trips:
#: nothing settled, something settled, everything settled, something wrong with
#: it, stages ruled out, and a route with more than one stop.
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

SURFACES = ("inline", "sidebar", "home")
VARIANTS = ("express-modular",)

#: Every prompt the golden holds, in the order it holds them.
LABELS: list[str] = [
    *(f"{name} / {surface}" for name in TRIPS for surface in SURFACES),
    *(f"variant / {variant}" for variant in VARIANTS),
]


def build(label: str) -> str:
    """Rebuilds one golden prompt from its label.

    The labels encode the case, so there is one table of trips rather than two
    that can disagree about what "ready" means — which is exactly what happened
    the first time this script and its test each kept their own copy.
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
    return skills.build_system_prompt(
        variant="express-modular",
        surface=rest,
        surface_id="inline-1" if rest == "inline" else rest,
        catalog_id="travel",
        trip=TRIPS[kind],
        today=TODAY,
    )


#: The cases kept in full, because a digest tells you *that* something moved
#: and not what.
#:
#: One trip at its emptiest and one with everything decided: between them they
#: contain every section the assembly can emit — the inventory, the control
#: table, the surface brief, the trip description with and without decisions,
#: and the "do this next" sentence in both its shapes.
IN_FULL = ("empty / inline", "ready / sidebar")


def capture() -> dict:
    """The golden: a digest per case, and two prompts kept whole.

    It used to be twenty-four prompts in full — 1.16 MB of checked-in JSON, and
    every intentional edit to `prompts/role.md` produced a diff no human read.
    That is the failure mode a golden exists to prevent, arriving by a different
    road: nobody reviews a hundred-thousand-line diff, so nobody would have seen
    an unintended change hiding in one.

    A digest catches the same drift in a line. The two full prompts are there so
    that when a digest moves you can *see* the change in the same commit rather
    than having to reproduce it.
    """
    return {
        "digests": {
            label: hashlib.sha256(build(label).encode("utf-8")).hexdigest()
            for label in LABELS
        },
        "inFull": {label: build(label) for label in IN_FULL},
        "skills": skills.describe_all_skills(),
    }


def main() -> int:
    fresh = capture()
    checking = "--check" in sys.argv

    if checking:
        if not GOLDEN.exists():
            print(f"No golden at {GOLDEN}. Run without --check to record one.", file=sys.stderr)
            return 1
        current = json.loads(GOLDEN.read_text("utf-8"))
        if current == fresh:
            print(f"{len(fresh['digests'])} prompts match their golden.")
            return 0
        changed = sorted(
            name
            for name in set(current.get("digests", {})) | set(fresh["digests"])
            if current.get("digests", {}).get(name) != fresh["digests"].get(name)
        )
        print("The prompt golden is out of date. Changed:", file=sys.stderr)
        for name in changed:
            print(f"  - {name}", file=sys.stderr)
        print("\nRe-record with: python3 tools/parity/capture.py", file=sys.stderr)
        return 1

    GOLDEN.write_text(json.dumps(fresh, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"Wrote {len(fresh['digests'])} digests and {len(IN_FULL)} prompts to {GOLDEN}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
