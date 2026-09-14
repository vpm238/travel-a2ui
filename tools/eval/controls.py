"""When something is missing, does the turn draw the control for it?

Written to check a reported failure — "what dates do you have in mind?", asked
in prose with no surface — and it found a different one. When this fails it
usually draws the *wrong* surface: stat tiles, a progress meter, a map. All of
it compiles, none of it has anywhere to put a date, and it looks like a turn
that worked. Which is why every run prints the components it drew.

Three openings, each run N times: one hop, a party that differs on the way back,
and a multi-city route where somebody joins partway. Scored on what was drawn,
never on what was said.

**Use twelve runs or more.** At six the variance swamps the effect: the same
code scored 67% on one eighteen-run sample and 17% on a thirty-six-run one, and
an afternoon went into tuning against the first of those. Twelve per scenario is
the floor for telling an improvement from a lucky sample.

Where it stands, measured at twelve:

    drew a surface           31/36  (86%)
    drew the right controls  23/36  (64%)

From 30/36 and 17/36 (47%), after two host bugs that this eval had been
blaming on the model:

  - `DateTimeInput` led with an optional `label`, so the natural one-argument
    call bound the path to the label, left `value` unset, and failed
    whole-message validation — taking the entire surface with it.
  - A capacity failure arriving *mid-stream* went past the retry and the
    fallback, both of which only guard the opening call. Of eight blank turns
    re-run with the failure printed, six were this.

64% is better and still not reliable, and should not be described as such. The
failures that remain are the original complaint: a dashboard drawn with
nowhere to put a date.

Read the two numbers as separate samples of the same size, not as a controlled
comparison — the variance that burned an afternoon here is still there.

Needs a key and spends tokens, so it is not part of the end-to-end suite.

    python3 tools/eval/controls.py "$GEMINI_API_KEY" 12
"""


import asyncio
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "server" / "src"))

from travel_a2ui.doors.interactions import (  # noqa: E402
    DEFAULT_MODEL,
    TurnRequest,
    run_turn,
)

KEY = sys.argv[1]
RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 5

#: Each case: what is said, what the turn is missing, and what it has to draw.
CASES = [
    {
        "name": "one hop, no dates",
        "message": "plan me a trip from SFO to NYC",
        "wants": {"DateRangePicker"},
        "counters": 1,
    },
    {
        "name": "party differs on the way back",
        "message": "plan me a trip from SFO to NYC and on the way back I need 2 tickets",
        "wants": {"DateRangePicker"},
        "counters": 2,
    },
    {
        "name": "multi-city, party grows in Chicago",
        "message": (
            "I want to fly SFO to Chicago, then on to New York, then home — "
            "and my partner joins me in Chicago"
        ),
        # A hop's date is a date, not a range: four cities is four departure
        # dates. Either control counts as having asked.
        "wants": {"DateRangePicker", "DateTimeInput"},
        "counters": 2,
    },
]


def components_of(events: list[dict]) -> list[str]:
    """Every component kind the turn actually drew."""
    kinds: list[str] = []
    for event in events:
        if event.get("type") != "ui":
            continue
        for message in event.get("messages") or []:
            for component in (message.get("updateComponents") or {}).get("components", []):
                kind = component.get("component")
                if kind:
                    kinds.append(kind)
    return kinds


async def once(case: dict, n: int) -> dict:
    events: list[dict] = []
    said: list[str] = []
    request = TurnRequest(
        api_key=KEY,
        model=DEFAULT_MODEL,
        message=case["message"],
        trip={},
        surface="inline",
        surface_id="inline-1",
    )
    async for event in run_turn(request):
        events.append(event)
        if event.get("type") == "text":
            said.append(event.get("delta") or "")

    kinds = components_of(events)
    prose = "".join(said)
    drew = bool(kinds)
    # Any one of the controls that can carry this case's answer.
    has_wanted = bool(case["wants"] & set(kinds))
    counters = kinds.count("TravelerCounter")
    # A question with nothing drawn is the reported failure exactly.
    asked_in_prose = "?" in prose and not drew

    print(
        f"  run {n}: drew={'yes' if drew else 'NO '} "
        f"dates={'yes' if has_wanted else 'NO '} "
        f"counters={counters}/{case['counters']} "
        f"{'ASKED IN PROSE' if asked_in_prose else ''}"
    )
    if drew:
        from collections import Counter
        print(f"         drew: {dict(Counter(kinds))}")
    else:
        print(f"         > {prose.strip()[:150]}")
    return {
        "drew": drew,
        "dates": has_wanted,
        "counters_ok": counters >= case["counters"],
        "prose": asked_in_prose,
    }


async def main() -> None:
    totals: dict[str, list] = defaultdict(list)
    for case in CASES:
        print(f"\n{case['name']}  —  {case['message'][:70]}")
        for n in range(RUNS):
            totals[case["name"]].append(await once(case, n + 1))

    print("\n" + "=" * 68)
    for name, runs in totals.items():
        drew = sum(r["drew"] for r in runs)
        dates = sum(r["dates"] for r in runs)
        counters = sum(r["counters_ok"] for r in runs)
        prose = sum(r["prose"] for r in runs)
        print(
            f"{name:38} drew {drew}/{len(runs)}  dates {dates}/{len(runs)}  "
            f"per-leg counters {counters}/{len(runs)}  asked in prose {prose}"
        )
    flat = [r for runs in totals.values() for r in runs]
    print(
        f"\noverall: drew {sum(r['drew'] for r in flat)}/{len(flat)}, "
        f"right controls {sum(r['dates'] and r['counters_ok'] for r in flat)}/{len(flat)}"
    )


asyncio.run(main())
